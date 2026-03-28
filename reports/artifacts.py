from __future__ import annotations

import json
from collections import defaultdict, deque
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from quantlab.config import AppPaths
from quantlab.registry import bootstrap_registry
from quantlab.schemas import (
    AnnualReturnPoint,
    BacktestMetrics,
    BacktestResult,
    BacktestRunConfig,
    DrawdownPoint,
    EquityPoint,
    RunArtifactManifest,
    RunStatus,
    TradeRecord,
)
from quantlab.storage import ARTIFACT_FILE_NAMES, ensure_state_dirs, run_dir

_REPLAY_DIAGNOSTICS_FILE_NAME = "replay_diagnostics.json"
_TRADE_SLICES_FILE_NAME = "trade_slices.parquet"


class ReplayTradeSlice(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    entry_trade_date: date
    exit_trade_date: date
    holding_days: int
    shares: int
    entry_price: float
    exit_price: float
    gross_pnl: float
    net_pnl: float
    return_pct: float
    entry_notes: str | None = None
    exit_notes: str | None = None


class ReplayDataHealth(BaseModel):
    model_config = ConfigDict(frozen=True)

    equity_points: int
    trade_count: int
    closed_trade_count: int
    open_lots: int
    unique_symbols: int
    first_trade_date: date | None = None
    last_trade_date: date | None = None
    warnings: list[str] = Field(default_factory=list)


class ReplayDiagnosticPayload(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    generated_at: datetime
    data_health: ReplayDataHealth
    trade_slices: list[ReplayTradeSlice]


def _artifact_path(artifact_dir: Path, artifact_name: str) -> Path:
    return artifact_dir / ARTIFACT_FILE_NAMES[artifact_name]


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))


def _write_records_parquet(path: Path, records: list[Any], model_type: type[Any]) -> None:
    rows = [record.model_dump(mode="json") for record in records]
    if rows:
        frame = pd.DataFrame(rows)
    else:
        frame = pd.DataFrame(columns=list(model_type.model_fields))
    frame.to_parquet(path, index=False)


def _load_records(path: Path, model_type: type[Any]) -> list[Any]:
    if not path.exists():
        return []
    frame = pd.read_parquet(path)
    return [model_type.model_validate(record) for record in frame.to_dict(orient="records")]


def _replay_diagnostics_path(paths: AppPaths, run_id: str) -> Path:
    return run_dir(paths, run_id) / _REPLAY_DIAGNOSTICS_FILE_NAME


def _trade_slices_path(paths: AppPaths, run_id: str) -> Path:
    return run_dir(paths, run_id) / _TRADE_SLICES_FILE_NAME


def _round_metric(value: float) -> float:
    return round(float(value), 6)


def _build_trade_slices(trades: list[TradeRecord]) -> tuple[list[ReplayTradeSlice], int]:
    lots_by_symbol: dict[str, deque[tuple[TradeRecord, int]]] = defaultdict(deque)
    slices: list[ReplayTradeSlice] = []

    for trade in sorted(trades, key=lambda item: (item.trade_date, item.symbol, item.side)):
        if trade.side == "buy":
            lots_by_symbol[trade.symbol].append((trade, trade.shares))
            continue

        remaining_shares = trade.shares
        sell_fee_remaining = trade.fees
        while remaining_shares > 0 and lots_by_symbol[trade.symbol]:
            entry_trade, available_shares = lots_by_symbol[trade.symbol][0]
            matched_shares = min(remaining_shares, available_shares)
            gross_pnl = (trade.price - entry_trade.price) * matched_shares
            net_pnl = gross_pnl - entry_trade.fees - sell_fee_remaining
            cost_basis = (entry_trade.price * matched_shares) + entry_trade.fees
            slices.append(
                ReplayTradeSlice(
                    symbol=trade.symbol,
                    entry_trade_date=entry_trade.trade_date,
                    exit_trade_date=trade.trade_date,
                    holding_days=max((trade.trade_date - entry_trade.trade_date).days, 0),
                    shares=matched_shares,
                    entry_price=entry_trade.price,
                    exit_price=trade.price,
                    gross_pnl=_round_metric(gross_pnl),
                    net_pnl=_round_metric(net_pnl),
                    return_pct=_round_metric(0.0 if cost_basis == 0 else net_pnl / cost_basis),
                    entry_notes=entry_trade.notes,
                    exit_notes=trade.notes,
                )
            )
            remaining_shares -= matched_shares
            sell_fee_remaining = 0.0
            if matched_shares == available_shares:
                lots_by_symbol[trade.symbol].popleft()
            else:
                lots_by_symbol[trade.symbol][0] = (entry_trade, available_shares - matched_shares)

    open_lots = sum(1 for lots in lots_by_symbol.values() for _ in lots)
    return slices, open_lots


def _build_replay_data_health(
    result: BacktestResult,
    trade_slices: list[ReplayTradeSlice],
    open_lots: int,
) -> ReplayDataHealth:
    warnings: list[str] = []
    if not result.equity_curve:
        warnings.append("No equity curve points were recorded for this run.")
    if result.trades and not trade_slices:
        warnings.append("Trades exist but no closed trade slices could be derived.")
    if open_lots > 0:
        warnings.append("Open lots remain after replay slice derivation.")

    trade_dates = [trade.trade_date for trade in result.trades]
    return ReplayDataHealth(
        equity_points=len(result.equity_curve),
        trade_count=len(result.trades),
        closed_trade_count=len(trade_slices),
        open_lots=open_lots,
        unique_symbols=len({trade.symbol for trade in result.trades}),
        first_trade_date=min(trade_dates) if trade_dates else None,
        last_trade_date=max(trade_dates) if trade_dates else None,
        warnings=warnings,
    )


def build_replay_diagnostic_payload(
    result: BacktestResult,
    *,
    generated_at: datetime | None = None,
) -> ReplayDiagnosticPayload:
    trade_slices, open_lots = _build_trade_slices(result.trades)
    return ReplayDiagnosticPayload(
        run_id=result.run_id,
        generated_at=generated_at or datetime.now(UTC),
        data_health=_build_replay_data_health(result, trade_slices, open_lots),
        trade_slices=trade_slices,
    )


def persist_backtest_result(paths: AppPaths, result: BacktestResult) -> RunArtifactManifest:
    ensure_state_dirs(paths)
    bootstrap_registry(paths.registry_path)
    artifact_dir = run_dir(paths, result.run_id)
    if artifact_dir.exists():
        raise FileExistsError(f"artifacts already exist for run_id={result.run_id}")
    artifact_dir.mkdir(parents=True, exist_ok=False)

    config_path = _artifact_path(artifact_dir, "config")
    metrics_path = _artifact_path(artifact_dir, "metrics")
    equity_curve_path = _artifact_path(artifact_dir, "equity_curve")
    drawdown_curve_path = _artifact_path(artifact_dir, "drawdown_curve")
    trades_path = _artifact_path(artifact_dir, "trades")
    annual_returns_path = _artifact_path(artifact_dir, "annual_returns")

    _write_json(config_path, result.config.model_dump(mode="json"))
    _write_json(metrics_path, result.metrics.model_dump(mode="json"))
    _write_records_parquet(equity_curve_path, result.equity_curve, EquityPoint)
    _write_records_parquet(drawdown_curve_path, result.drawdown_curve, DrawdownPoint)
    _write_records_parquet(trades_path, result.trades, TradeRecord)
    _write_records_parquet(annual_returns_path, result.annual_returns, AnnualReturnPoint)

    manifest = RunArtifactManifest(
        run_id=result.run_id,
        status=RunStatus.COMPLETED,
        config_path=str(config_path),
        metrics_path=str(metrics_path),
        equity_curve_path=str(equity_curve_path),
        drawdown_curve_path=str(drawdown_curve_path),
        trades_path=str(trades_path),
        annual_returns_path=str(annual_returns_path),
    )
    _write_json(_artifact_path(artifact_dir, "manifest"), manifest.model_dump(mode="json"))

    now = datetime.now(UTC)
    with duckdb.connect(str(paths.registry_path)) as connection:
        connection.execute(
            """
            insert into backtest_runs (
                run_id,
                strategy_name,
                start_date,
                end_date,
                execution_mode,
                status,
                created_at,
                completed_at,
                metrics_path,
                artifacts_dir
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                result.run_id,
                result.config.strategy_name,
                result.config.start_date,
                result.config.end_date,
                result.config.execution.mode.value,
                RunStatus.COMPLETED.value,
                now,
                now,
                str(metrics_path),
                str(artifact_dir),
            ],
        )
    return manifest


def persist_replay_diagnostic_payload(paths: AppPaths, payload: ReplayDiagnosticPayload) -> Path:
    artifact_dir = run_dir(paths, payload.run_id)
    if not artifact_dir.exists():
        raise FileNotFoundError(f"run artifacts do not exist for run_id={payload.run_id}")

    payload_path = _replay_diagnostics_path(paths, payload.run_id)
    if payload_path.exists():
        raise FileExistsError(f"replay diagnostics already exist for run_id={payload.run_id}")

    _write_json(payload_path, payload.model_dump(mode="json"))
    _write_records_parquet(_trade_slices_path(paths, payload.run_id), payload.trade_slices, ReplayTradeSlice)
    return payload_path


def load_backtest_result(paths: AppPaths, run_id: str) -> BacktestResult:
    artifact_dir = run_dir(paths, run_id)
    config = BacktestRunConfig.model_validate(json.loads(_artifact_path(artifact_dir, "config").read_text()))
    metrics = BacktestMetrics.model_validate(json.loads(_artifact_path(artifact_dir, "metrics").read_text()))
    equity_curve = _load_records(_artifact_path(artifact_dir, "equity_curve"), EquityPoint)
    drawdown_curve = _load_records(_artifact_path(artifact_dir, "drawdown_curve"), DrawdownPoint)
    trades = _load_records(_artifact_path(artifact_dir, "trades"), TradeRecord)
    annual_returns = _load_records(_artifact_path(artifact_dir, "annual_returns"), AnnualReturnPoint)
    return BacktestResult(
        run_id=run_id,
        config=config,
        metrics=metrics,
        equity_curve=equity_curve,
        drawdown_curve=drawdown_curve,
        trades=trades,
        annual_returns=annual_returns,
    )


def load_replay_diagnostic_payload(paths: AppPaths, run_id: str) -> ReplayDiagnosticPayload | None:
    payload_path = _replay_diagnostics_path(paths, run_id)
    if not payload_path.exists():
        return None
    return ReplayDiagnosticPayload.model_validate(json.loads(payload_path.read_text()))
