from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from itertools import product
from pathlib import Path
from uuid import uuid4

import duckdb
from pydantic import BaseModel, ConfigDict, Field

from backtest import prepare_backtest_data, run_backtest_with_prepared_data
from quantlab.config import AppPaths
from quantlab.registry import bootstrap_registry
from quantlab.schemas import (
    BacktestResult,
    BacktestRunConfig,
    ExecutionConfig,
    FeeConfig,
    PortfolioConfig,
    RuleConfig,
    StrategyParams,
    UniverseConfig,
)
from reports.artifacts import build_replay_diagnostic_payload, persist_backtest_result, persist_replay_diagnostic_payload

ScalarValue = str | int | float | bool

_NESTED_CONFIG_MODELS: tuple[tuple[str, type[BaseModel]], ...] = (
    ("strategy_params", StrategyParams),
    ("portfolio", PortfolioConfig),
    ("execution", ExecutionConfig),
    ("fees", FeeConfig),
    ("rules", RuleConfig),
    ("universe", UniverseConfig),
)
_MARKET_DATA_PATHS = {
    "start_date",
    "end_date",
    "timezone",
    "adjustment_mode",
    "universe.allowed_symbol_prefixes",
}


class ScanParameterSet(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    value: ScalarValue


class ScanRunSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    params: dict[str, ScalarValue]
    total_return_pct: float | None = None
    max_drawdown_pct: float | None = None
    trade_count: int = 0
    annualized_return_pct: float | None = None
    win_rate_pct: float | None = None
    turnover_ratio: float | None = None
    status: str = "completed"
    score: float | None = None
    rank: int | None = None
    error_message: str | None = None
    replay_available: bool = False


class ScanAggregateSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    requested_runs: int
    completed_runs: int
    failed_runs: int = 0
    best_run_id: str | None = None
    best_total_return_pct: float | None = None
    worst_max_drawdown_pct: float | None = None
    warnings: list[str] = Field(default_factory=list)


class ScanBatchResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    scan_batch_id: str
    strategy_name: str
    created_at: datetime
    parameter_sets: list[ScanParameterSet]
    runs: list[ScanRunSummary]
    parameter_names: list[str] = Field(default_factory=list)
    best_run_id: str | None = None
    aggregate: ScanAggregateSummary | None = None


def _scans_root(paths: AppPaths) -> Path:
    root = paths.local_state_dir / "scans"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _scan_result_path(paths: AppPaths, scan_batch_id: str) -> Path:
    return _scans_root(paths) / f"{scan_batch_id}.json"


def _expand_parameter_grid(parameter_grid: Mapping[str, Sequence[ScalarValue]]) -> list[dict[str, ScalarValue]]:
    if not parameter_grid:
        return [{}]

    ordered_items = [(name, list(values)) for name, values in parameter_grid.items()]
    for name, values in ordered_items:
        if not values:
            raise ValueError(f"parameter_grid[{name!r}] must include at least one value")

    names = [name for name, _ in ordered_items]
    combinations: list[dict[str, ScalarValue]] = []
    for combination in product(*(values for _, values in ordered_items)):
        combinations.append(dict(zip(names, combination, strict=True)))
    return combinations


def _parameter_axes(parameter_grid: Mapping[str, Sequence[ScalarValue]]) -> list[ScanParameterSet]:
    axes: list[ScanParameterSet] = []
    for name in sorted(parameter_grid):
        seen: set[ScalarValue] = set()
        for value in parameter_grid[name]:
            if value in seen:
                continue
            axes.append(ScanParameterSet(name=name, value=value))
            seen.add(value)
    return axes


def _resolve_param_path(config: BacktestRunConfig, name: str) -> tuple[str, ...]:
    if "." in name:
        path = tuple(segment for segment in name.split(".") if segment)
        if not path:
            raise ValueError(f"invalid parameter name {name!r}")
        return path

    if name in type(config).model_fields:
        return (name,)

    matches = [root_name for root_name, model_type in _NESTED_CONFIG_MODELS if name in model_type.model_fields]
    if len(matches) == 1:
        return (matches[0], name)
    if matches:
        raise ValueError(f"parameter name {name!r} is ambiguous; use dotted notation")
    raise ValueError(f"parameter name {name!r} does not map to BacktestRunConfig")


def _apply_param(payload: dict[str, object], path: tuple[str, ...], value: ScalarValue) -> None:
    cursor = payload
    for segment in path[:-1]:
        next_cursor = cursor.get(segment)
        if not isinstance(next_cursor, dict):
            raise ValueError(f"scan parameter path {'.'.join(path)!r} is not writable")
        cursor = next_cursor
    cursor[path[-1]] = value


def _build_scan_run_config(
    base_config: BacktestRunConfig,
    scan_batch_id: str,
    run_index: int,
    params: dict[str, ScalarValue],
) -> BacktestRunConfig:
    payload = base_config.model_dump(mode="python")
    for name, value in params.items():
        _apply_param(payload, _resolve_param_path(base_config, name), value)
    payload["run_id"] = f"{scan_batch_id}-{run_index:03d}"
    return BacktestRunConfig.model_validate(payload)


def _market_data_signature(config: BacktestRunConfig) -> tuple[object, ...]:
    values: list[object] = []
    payload = config.model_dump(mode="python")
    for path in sorted(_MARKET_DATA_PATHS):
        cursor: object = payload
        for segment in path.split("."):
            if not isinstance(cursor, dict):
                cursor = None
                break
            cursor = cursor.get(segment)
        if isinstance(cursor, list):
            cursor = tuple(cursor)
        values.append(cursor)
    return tuple(values)


def _run_summary(
    result: BacktestResult | None,
    params: dict[str, ScalarValue],
    *,
    run_id: str,
    error_message: str | None = None,
    replay_available: bool = False,
) -> ScanRunSummary:
    if result is None:
        return ScanRunSummary(
            run_id=run_id,
            params=params,
            status="failed",
            score=None,
            error_message=error_message,
            replay_available=replay_available,
        )

    return ScanRunSummary(
        run_id=result.run_id,
        params=params,
        total_return_pct=result.metrics.total_return_pct,
        max_drawdown_pct=result.metrics.max_drawdown_pct,
        trade_count=result.metrics.trade_count,
        annualized_return_pct=result.metrics.annualized_return_pct,
        win_rate_pct=result.metrics.win_rate_pct,
        turnover_ratio=result.metrics.turnover_ratio,
        status="completed",
        score=result.metrics.total_return_pct,
        replay_available=replay_available,
    )


def _rank_runs(runs: list[ScanRunSummary]) -> list[ScanRunSummary]:
    def sort_key(item: ScanRunSummary) -> tuple[float, float, float, int]:
        return (
            float(item.score if item.score is not None else float("-inf")),
            float(item.max_drawdown_pct if item.max_drawdown_pct is not None else float("-inf")),
            float(item.annualized_return_pct if item.annualized_return_pct is not None else float("-inf")),
            -item.trade_count,
        )

    ranked_runs: list[ScanRunSummary] = []
    for index, run in enumerate(sorted(runs, key=sort_key, reverse=True), start=1):
        ranked_runs.append(run.model_copy(update={"rank": index}))
    return ranked_runs


def _aggregate_runs(runs: Sequence[ScanRunSummary]) -> ScanAggregateSummary:
    completed = [run for run in runs if run.status == "completed"]
    warnings: list[str] = []
    if not completed:
        warnings.append("No scan runs completed successfully.")

    best_run = completed[0] if completed else None
    worst_drawdown = min((run.max_drawdown_pct for run in completed if run.max_drawdown_pct is not None), default=None)
    best_return = max((run.total_return_pct for run in completed if run.total_return_pct is not None), default=None)
    return ScanAggregateSummary(
        requested_runs=len(runs),
        completed_runs=len(completed),
        failed_runs=len(runs) - len(completed),
        best_run_id=best_run.run_id if best_run is not None else None,
        best_total_return_pct=best_return,
        worst_max_drawdown_pct=worst_drawdown,
        warnings=warnings,
    )


def persist_scan_batch_result(paths: AppPaths, batch: ScanBatchResult) -> Path:
    bootstrap_registry(paths.registry_path)
    result_path = _scan_result_path(paths, batch.scan_batch_id)
    if result_path.exists():
        raise FileExistsError(f"scan batch already exists for scan_batch_id={batch.scan_batch_id}")
    result_path.write_text(json.dumps(batch.model_dump(mode="json"), indent=2, sort_keys=True))
    with duckdb.connect(str(paths.registry_path)) as connection:
        connection.execute(
            """
            insert into scan_batches (
                scan_batch_id,
                strategy_name,
                created_at,
                result_path
            ) values (?, ?, ?, ?)
            """,
            [batch.scan_batch_id, batch.strategy_name, batch.created_at, str(result_path)],
        )
    return result_path


def load_scan_batch_result(paths: AppPaths, scan_batch_id: str) -> ScanBatchResult:
    return ScanBatchResult.model_validate(json.loads(_scan_result_path(paths, scan_batch_id).read_text()))


def run_parameter_scan(
    *,
    paths: AppPaths,
    base_config: BacktestRunConfig,
    parameter_grid: Mapping[str, Sequence[ScalarValue]],
    scan_batch_id: str | None = None,
    persist_runs: bool = False,
    persist_batch: bool = False,
    persist_replay_diagnostics: bool = False,
) -> ScanBatchResult:
    batch_id = scan_batch_id or uuid4().hex
    combinations = _expand_parameter_grid(parameter_grid)
    parameter_names = sorted(parameter_grid)
    created_at = datetime.now(UTC)

    prepared_data = prepare_backtest_data(paths, base_config)
    prepared_signature = _market_data_signature(base_config)
    run_summaries: list[ScanRunSummary] = []

    for run_index, params in enumerate(combinations, start=1):
        run_config = _build_scan_run_config(base_config, batch_id, run_index, params)
        run_signature = _market_data_signature(run_config)
        if run_signature != prepared_signature:
            prepared_data = prepare_backtest_data(paths, run_config)
            prepared_signature = run_signature

        replay_available = False
        try:
            result = run_backtest_with_prepared_data(prepared_data, run_config)
            if persist_runs:
                persist_backtest_result(paths, result)
            if persist_replay_diagnostics:
                persist_replay_diagnostic_payload(paths, build_replay_diagnostic_payload(result))
                replay_available = True
        except Exception as exc:
            run_summaries.append(
                _run_summary(
                    None,
                    params,
                    run_id=run_config.run_id,
                    error_message=str(exc),
                    replay_available=replay_available,
                )
            )
            continue

        run_summaries.append(
            _run_summary(
                result,
                params,
                run_id=run_config.run_id,
                replay_available=replay_available,
            )
        )

    ranked_runs = _rank_runs(run_summaries)
    aggregate = _aggregate_runs(ranked_runs)
    batch = ScanBatchResult(
        scan_batch_id=batch_id,
        strategy_name=base_config.strategy_name,
        created_at=created_at,
        parameter_sets=_parameter_axes(parameter_grid),
        runs=ranked_runs,
        parameter_names=parameter_names,
        best_run_id=aggregate.best_run_id,
        aggregate=aggregate,
    )
    if persist_batch:
        persist_scan_batch_result(paths, batch)
    return batch
