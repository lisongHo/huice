from __future__ import annotations

import json
from collections import defaultdict, deque
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from data.providers.tushare_readiness import collect_tushare_readiness, tushare_readiness_to_dict
from data.providers.tushare_readiness import classify_tushare_planning_blocker, format_tushare_planning_blocker
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
    SyncArtifactManifest,
    SyncRunRequest,
    SyncWorkflow,
    TradeRecord,
)
from quantlab.storage import (
    ARTIFACT_FILE_NAMES,
    ensure_state_dirs,
    readiness_artifact_path,
    readiness_root,
    readiness_snapshot_path,
    run_dir,
    sync_run_dir,
)
from data.ingest.sync import execute_sync_request as execute_sync_request_payload
from data.ingest.sync import validate_minute_data

_REPLAY_DIAGNOSTICS_FILE_NAME = "replay_diagnostics.json"
_TRADE_SLICES_FILE_NAME = "trade_slices.parquet"
_SYNC_REQUEST_FILE_NAME = "request.json"
_SYNC_SUMMARY_FILE_NAME = "summary.json"
_SYNC_MANIFEST_FILE_NAME = "manifest.json"
_SYNC_VALIDATION_FILE_NAME = "validation.json"


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


class SyncRunRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    sync_run_id: str
    workflow: SyncWorkflow
    status: RunStatus
    requested_at: datetime
    completed_at: datetime | None = None
    summary_path: str
    artifact_dir: str


class SyncRunPayload(BaseModel):
    model_config = ConfigDict(frozen=True)

    manifest: SyncArtifactManifest
    request: SyncRunRequest
    summary: dict[str, Any]
    validation: dict[str, Any] | None = None


def _artifact_path(artifact_dir: Path, artifact_name: str) -> Path:
    return artifact_dir / ARTIFACT_FILE_NAMES[artifact_name]


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))


def _readiness_snapshot_timestamp() -> datetime:
    return datetime.now(UTC)


def _readiness_snapshot_name(timestamp: datetime) -> str:
    return timestamp.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ.json")


def _sync_summary_window(summary: dict[str, Any]) -> tuple[str | None, str | None]:
    minute_windows = summary.get("minute_windows")
    if not isinstance(minute_windows, list) or not minute_windows:
        return None, None

    start_dates = [str(item.get("start_date")) for item in minute_windows if isinstance(item, dict) and item.get("start_date")]
    end_dates = [str(item.get("end_date")) for item in minute_windows if isinstance(item, dict) and item.get("end_date")]
    return (min(start_dates) if start_dates else None, max(end_dates) if end_dates else None)


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


def _sync_run_artifact_dir(paths: AppPaths, sync_run_id: str) -> Path:
    return sync_run_dir(paths, sync_run_id)


def _sync_run_path(paths: AppPaths, sync_run_id: str, file_name: str) -> Path:
    return _sync_run_artifact_dir(paths, sync_run_id) / file_name


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


def persist_sync_run_result(
    paths: AppPaths,
    request: SyncRunRequest,
    summary: dict[str, Any],
    *,
    validation: dict[str, Any] | None = None,
    requested_at: datetime | None = None,
    completed_at: datetime | None = None,
    status: RunStatus = RunStatus.COMPLETED,
) -> SyncArtifactManifest:
    ensure_state_dirs(paths)
    bootstrap_registry(paths.registry_path)

    artifact_dir = _sync_run_artifact_dir(paths, request.sync_run_id)
    if artifact_dir.exists():
        raise FileExistsError(f"artifacts already exist for sync_run_id={request.sync_run_id}")
    artifact_dir.mkdir(parents=True, exist_ok=False)

    request_path = _sync_run_path(paths, request.sync_run_id, _SYNC_REQUEST_FILE_NAME)
    summary_path = _sync_run_path(paths, request.sync_run_id, _SYNC_SUMMARY_FILE_NAME)
    manifest_path = _sync_run_path(paths, request.sync_run_id, _SYNC_MANIFEST_FILE_NAME)
    validation_path = (
        _sync_run_path(paths, request.sync_run_id, _SYNC_VALIDATION_FILE_NAME) if validation is not None else None
    )

    _write_json(request_path, request.model_dump(mode="json"))
    _write_json(summary_path, summary)
    if validation_path is not None:
        _write_json(validation_path, validation)

    manifest = SyncArtifactManifest(
        sync_run_id=request.sync_run_id,
        workflow=request.workflow,
        status=status,
        request_path=str(request_path),
        summary_path=str(summary_path),
        validation_path=str(validation_path) if validation_path is not None else None,
    )
    _write_json(manifest_path, manifest.model_dump(mode="json"))

    requested_at_value = requested_at or datetime.now(UTC)
    completed_at_value = completed_at if completed_at is not None else requested_at_value
    with duckdb.connect(str(paths.registry_path)) as connection:
        connection.execute(
            """
            insert into sync_runs (
                sync_run_id,
                workflow,
                status,
                requested_at,
                completed_at,
                summary_path,
                artifact_dir
            ) values (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                request.sync_run_id,
                request.workflow.value,
                status.value,
                requested_at_value,
                completed_at_value,
                str(summary_path),
                str(artifact_dir),
            ],
        )
    return manifest


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


def load_recent_sync_runs(paths: AppPaths, *, limit: int = 10) -> list[SyncRunRecord]:
    ensure_state_dirs(paths)
    if limit <= 0:
        return []

    with duckdb.connect(str(paths.registry_path)) as connection:
        rows = connection.execute(
            """
            select
                sync_run_id,
                workflow,
                status,
                requested_at,
                completed_at,
                summary_path,
                artifact_dir
            from sync_runs
            order by requested_at desc, sync_run_id desc
            limit ?
            """,
            [limit],
        ).fetchall()

    return [
        SyncRunRecord.model_validate(
            {
                "sync_run_id": row[0],
                "workflow": row[1],
                "status": row[2],
                "requested_at": row[3],
                "completed_at": row[4],
                "summary_path": row[5],
                "artifact_dir": row[6],
            }
        )
        for row in rows
    ]


def load_sync_run_payload(paths: AppPaths, sync_run_id: str) -> SyncRunPayload | None:
    manifest_path = _sync_run_path(paths, sync_run_id, _SYNC_MANIFEST_FILE_NAME)
    if not manifest_path.exists():
        return None

    manifest = SyncArtifactManifest.model_validate(json.loads(manifest_path.read_text()))
    request = SyncRunRequest.model_validate(
        json.loads(_sync_run_path(paths, sync_run_id, _SYNC_REQUEST_FILE_NAME).read_text())
    )
    summary = json.loads(_sync_run_path(paths, sync_run_id, _SYNC_SUMMARY_FILE_NAME).read_text())
    validation_path = _sync_run_path(paths, sync_run_id, _SYNC_VALIDATION_FILE_NAME)
    validation = json.loads(validation_path.read_text()) if validation_path.exists() else None
    return SyncRunPayload(
        manifest=manifest,
        request=request,
        summary=summary,
        validation=validation,
    )


def persist_latest_readiness_payload(paths: AppPaths, payload: dict[str, Any]) -> Path:
    ensure_state_dirs(paths)
    artifact_path = readiness_artifact_path(paths)
    artifact_path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    snapshot_name = _readiness_snapshot_name(_readiness_snapshot_timestamp())
    readiness_snapshot_path(paths, snapshot_name).write_text(json.dumps(payload, indent=2, sort_keys=True))
    return artifact_path


def load_latest_readiness_payload(paths: AppPaths) -> dict[str, Any] | None:
    artifact_path = readiness_artifact_path(paths)
    if not artifact_path.exists():
        return None
    return json.loads(artifact_path.read_text())


def load_recent_readiness_artifacts(paths: AppPaths, *, limit: int = 10) -> list[tuple[Path, dict[str, Any]]]:
    ensure_state_dirs(paths)
    snapshot_paths = [
        path
        for path in readiness_root(paths).glob("*.json")
        if path.name != "latest.json"
    ]
    snapshot_paths.sort(key=lambda path: path.name, reverse=True)
    return [(path, json.loads(path.read_text())) for path in snapshot_paths[:limit]]


def run_provider_readiness_check(
    paths: AppPaths,
    *,
    config_path: Path | None = None,
    reference_date: str | None = None,
) -> dict[str, Any]:
    report = collect_tushare_readiness(config_path=config_path, reference_date=reference_date)
    payload = tushare_readiness_to_dict(report)
    persist_latest_readiness_payload(paths, payload)
    return payload


def run_sync(
    paths: AppPaths,
    request: SyncRunRequest | dict[str, Any],
) -> dict[str, Any]:
    execution = execute_sync_request_payload(paths=paths, request_payload=request)

    status = RunStatus.COMPLETED if execution.success else RunStatus.FAILED
    validation_payload: dict[str, Any] | None = None
    if execution.success and not execution.request.dry_run:
        validation_start_date, validation_end_date = _sync_summary_window(execution.summary_payload)
        try:
            validation_payload = validate_minute_data(
                paths=paths,
                start_date=validation_start_date or execution.request.start_date,
                end_date=validation_end_date or execution.request.end_date,
                symbols=execution.request.symbols,
            )
        except Exception as exc:  # pragma: no cover - defensive guard for artifact enrichment
            validation_payload = {
                "status": "failed",
                "error_type": exc.__class__.__name__,
                "error": str(exc),
            }

    manifest = persist_sync_run_result(
        paths=paths,
        request=execution.request,
        summary=execution.summary_payload,
        validation=validation_payload,
        status=status,
    )

    message = "Sync execution completed and artifacts were persisted."
    next_steps: list[str] = []
    if execution.error is not None:
        blocker = classify_tushare_planning_blocker(execution.error)
        if blocker is not None:
            message = format_tushare_planning_blocker(
                blocker,
                workflow=execution.request.workflow.value.replace("-", " ").title(),
                dry_run=execution.request.dry_run,
            )
            next_steps = list(blocker.next_steps)
        else:
            message = f"Sync execution failed: {execution.summary_payload.get('error', str(execution.error))}"
    elif validation_payload is not None and validation_payload.get("failed_error_checks"):
        message = "Sync execution completed, but validation found failed error checks."
        next_steps = [
            "Open the saved validation artifact and review failed error checks.",
            "Run Data Health after inspecting the new minute-bar partitions.",
        ]

    return {
        "success": execution.success,
        "message": message,
        "sync_run_id": execution.request.sync_run_id,
        "artifact_path": str(sync_run_dir(paths, execution.request.sync_run_id)),
        "summary_path": manifest.summary_path,
        "payload": execution.summary_payload,
        "request": execution.request.model_dump(mode="json"),
        "validation": validation_payload,
        "next_steps": next_steps,
        "error": None if execution.error is None else str(execution.error),
    }
