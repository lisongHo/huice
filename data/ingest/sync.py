from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Sequence

import pandas as pd

from data.ingest.publish import publish_from_provider
from data.providers.tushare_provider import (
    TushareConfigurationError,
    TushareProProvider,
    build_tushare_provider,
    load_tushare_config,
    restrict_stock_symbols,
)
from data.quality.checks import QualityCheckResult, run_quality_checks
from data.store.duckdb_registry import (
    finish_ingestion_run,
    record_file_manifest,
    record_validation_results,
    start_ingestion_run,
)
from data.store.parquet_store import read_dataset, write_dataset
from quantlab.config import AppPaths
from quantlab.storage import ensure_state_dirs

REFERENCE_DATASETS: tuple[str, ...] = ("security_master", "trade_calendar")
EXPECTED_BARS_PER_DAY = 240


@dataclass(frozen=True)
class SyncWindow:
    start_date: date
    end_date: date
    trade_dates: tuple[str, ...]
    symbol_count: int
    expected_rows: int
    reason: str


@dataclass(frozen=True)
class GapIssue:
    trade_date: str
    symbol: str
    actual_bars: int
    expected_bars: int = EXPECTED_BARS_PER_DAY


@dataclass(frozen=True)
class GapScanResult:
    expected_trade_dates: tuple[str, ...]
    expected_symbol_count: int
    issue_count: int
    affected_trade_dates: tuple[str, ...]
    issues: tuple[GapIssue, ...]


@dataclass(frozen=True)
class SyncPlan:
    workflow: str
    config_path: str | None
    dry_run: bool
    start_date: str
    end_date: str
    symbol_count: int
    windows: tuple[SyncWindow, ...]
    reference_datasets: tuple[str, ...]
    gap_scan: GapScanResult | None = None


@dataclass(frozen=True)
class SyncRunSummary:
    workflow: str
    reference_sync: dict[str, int]
    minute_windows: tuple[dict[str, object], ...]
    gap_scan: GapScanResult | None = None


def build_provider(config_path: Path | None = None) -> TushareProProvider:
    return build_tushare_provider(config_path=config_path)


def build_backfill_plan(
    paths: AppPaths,
    start_date: date | str,
    end_date: date | str,
    config_path: Path | None = None,
    symbols: Sequence[str] | None = None,
    dry_run: bool = True,
) -> SyncPlan:
    provider = build_provider(config_path=config_path)
    config = load_tushare_config(config_path=config_path)
    normalized_start = pd.Timestamp(start_date).date()
    normalized_end = pd.Timestamp(end_date).date()
    universe = resolve_symbol_universe(paths=paths, provider=provider, symbols=symbols, plan_only=dry_run)
    trade_dates = resolve_open_trade_dates(
        paths=paths,
        provider=provider,
        start_date=normalized_start,
        end_date=normalized_end,
        plan_only=dry_run,
    )
    windows = tuple(
        SyncWindow(
            start_date=chunk[0],
            end_date=chunk[-1],
            trade_dates=tuple(day.isoformat() for day in chunk),
            symbol_count=len(universe),
            expected_rows=len(universe) * len(chunk) * EXPECTED_BARS_PER_DAY,
            reason="initial_backfill",
        )
        for chunk in chunk_trade_dates(trade_dates, config.minute_chunk_days)
    )
    return SyncPlan(
        workflow="backfill",
        config_path=str(config_path) if config_path else None,
        dry_run=dry_run,
        start_date=normalized_start.isoformat(),
        end_date=normalized_end.isoformat(),
        symbol_count=len(universe),
        windows=windows,
        reference_datasets=REFERENCE_DATASETS,
    )


def run_backfill(
    paths: AppPaths,
    start_date: date | str,
    end_date: date | str,
    config_path: Path | None = None,
    symbols: Sequence[str] | None = None,
    dry_run: bool = False,
) -> SyncPlan | SyncRunSummary:
    plan = build_backfill_plan(
        paths=paths,
        start_date=start_date,
        end_date=end_date,
        config_path=config_path,
        symbols=symbols,
        dry_run=dry_run,
    )
    if dry_run:
        return plan

    provider = build_provider(config_path=config_path)
    reference_summary = sync_reference_datasets(
        paths=paths,
        provider=provider,
        start_date=start_date,
        end_date=end_date,
    )
    symbols_to_sync = resolve_symbol_universe(paths=paths, provider=provider, symbols=symbols, plan_only=False)
    minute_windows = tuple(
        sync_minute_window(
            paths=paths,
            provider=provider,
            symbols=symbols_to_sync,
            window=window,
            reason=window.reason,
        )
        for window in plan.windows
    )
    return SyncRunSummary(workflow="backfill", reference_sync=reference_summary, minute_windows=minute_windows)


def build_refresh_plan(
    paths: AppPaths,
    end_date: date | str | None = None,
    workflow: str = "daily-refresh",
    config_path: Path | None = None,
    symbols: Sequence[str] | None = None,
    dry_run: bool = True,
) -> SyncPlan:
    provider = build_provider(config_path=config_path)
    config = load_tushare_config(config_path=config_path)
    normalized_end = pd.Timestamp(end_date or date.today()).date()
    universe = resolve_symbol_universe(paths=paths, provider=provider, symbols=symbols, plan_only=dry_run)
    lookback_days = (
        config.maintenance_lookback_open_days
        if workflow == "weekly-maintenance"
        else config.refresh_lookback_open_days
    )
    trade_dates = resolve_open_trade_dates(
        paths=paths,
        provider=provider,
        start_date=normalized_end - timedelta(days=max(lookback_days * 3, 10)),
        end_date=normalized_end,
        plan_only=dry_run,
    )
    selected_trade_dates = trade_dates[-lookback_days:] if trade_dates else []
    if not selected_trade_dates:
        raise TushareConfigurationError("no trade dates available for refresh planning")

    windows = tuple(
        SyncWindow(
            start_date=chunk[0],
            end_date=chunk[-1],
            trade_dates=tuple(day.isoformat() for day in chunk),
            symbol_count=len(universe),
            expected_rows=len(universe) * len(chunk) * EXPECTED_BARS_PER_DAY,
            reason=workflow,
        )
        for chunk in chunk_trade_dates(selected_trade_dates, config.minute_chunk_days)
    )
    gap_scan = None
    if workflow == "weekly-maintenance":
        gap_scan = scan_minute_bar_gaps(
            paths=paths,
            trade_dates=selected_trade_dates,
            expected_symbols=universe,
        )
        if gap_scan.affected_trade_dates:
            affected_dates = [pd.Timestamp(value).date() for value in gap_scan.affected_trade_dates]
            windows = tuple(
                SyncWindow(
                    start_date=chunk[0],
                    end_date=chunk[-1],
                    trade_dates=tuple(day.isoformat() for day in chunk),
                    symbol_count=len(universe),
                    expected_rows=len(universe) * len(chunk) * EXPECTED_BARS_PER_DAY,
                    reason="weekly_maintenance_gap_repair",
                )
                for chunk in chunk_trade_dates(affected_dates, config.minute_chunk_days)
            )
        else:
            windows = ()

    return SyncPlan(
        workflow=workflow,
        config_path=str(config_path) if config_path else None,
        dry_run=dry_run,
        start_date=selected_trade_dates[0].isoformat(),
        end_date=selected_trade_dates[-1].isoformat(),
        symbol_count=len(universe),
        windows=windows,
        reference_datasets=REFERENCE_DATASETS,
        gap_scan=gap_scan,
    )


def run_refresh(
    paths: AppPaths,
    end_date: date | str | None = None,
    workflow: str = "daily-refresh",
    config_path: Path | None = None,
    symbols: Sequence[str] | None = None,
    dry_run: bool = False,
) -> SyncPlan | SyncRunSummary:
    plan = build_refresh_plan(
        paths=paths,
        end_date=end_date,
        workflow=workflow,
        config_path=config_path,
        symbols=symbols,
        dry_run=dry_run,
    )
    if dry_run:
        return plan

    provider = build_provider(config_path=config_path)
    reference_summary = sync_reference_datasets(
        paths=paths,
        provider=provider,
        start_date=plan.start_date,
        end_date=plan.end_date,
    )
    symbols_to_sync = resolve_symbol_universe(paths=paths, provider=provider, symbols=symbols, plan_only=False)
    minute_windows = tuple(
        sync_minute_window(
            paths=paths,
            provider=provider,
            symbols=symbols_to_sync,
            window=window,
            reason=window.reason,
        )
        for window in plan.windows
    )
    return SyncRunSummary(
        workflow=workflow,
        reference_sync=reference_summary,
        minute_windows=minute_windows,
        gap_scan=plan.gap_scan,
    )


def sync_reference_datasets(
    paths: AppPaths,
    provider: TushareProProvider,
    start_date: date | str,
    end_date: date | str,
) -> dict[str, int]:
    ensure_state_dirs(paths)
    result = publish_from_provider(
        provider=provider,
        paths=paths,
        dataset_names=REFERENCE_DATASETS,
        start_date=start_date,
        end_date=end_date,
        notes="tushare_reference_sync",
    )
    return dict(result.datasets)


def sync_minute_window(
    paths: AppPaths,
    provider: TushareProProvider,
    symbols: Sequence[str],
    window: SyncWindow,
    reason: str,
) -> dict[str, object]:
    result = publish_from_provider(
        provider=provider,
        paths=paths,
        dataset_names=("minute_bars",),
        start_date=window.start_date,
        end_date=window.end_date,
        symbols=symbols,
        notes=f"tushare:{reason}:{window.start_date.isoformat()}:{window.end_date.isoformat()}",
    )
    return {
        "start_date": window.start_date.isoformat(),
        "end_date": window.end_date.isoformat(),
        "trade_dates": window.trade_dates,
        "row_counts": dict(result.datasets),
        "written_files": len(result.files),
    }


def resolve_symbol_universe(
    paths: AppPaths,
    provider: TushareProProvider,
    symbols: Sequence[str] | None = None,
    plan_only: bool = False,
) -> list[str]:
    explicit = restrict_stock_symbols(symbols)
    if explicit:
        return explicit

    configured = restrict_stock_symbols(provider.config.universe_symbols, prefixes=provider.config.prefixes)
    if configured:
        return configured

    local_master = read_dataset(paths, "security_master")
    if not local_master.empty and "symbol" in local_master.columns:
        return restrict_stock_symbols(local_master["symbol"].astype(str).tolist(), prefixes=provider.config.prefixes)

    if plan_only:
        raise TushareConfigurationError(
            "No local or configured universe is available for dry-run planning. "
            "Provide --symbols or add symbols under [universe] in the config."
        )

    remote_master = provider.get_security_master()
    if remote_master.empty:
        raise TushareConfigurationError("Tushare returned an empty security_master universe")
    return restrict_stock_symbols(remote_master["symbol"].astype(str).tolist(), prefixes=provider.config.prefixes)


def resolve_open_trade_dates(
    paths: AppPaths,
    provider: TushareProProvider,
    start_date: date,
    end_date: date,
    plan_only: bool = False,
) -> list[date]:
    if end_date < start_date:
        raise TushareConfigurationError("end_date must be on or after start_date")

    local_calendar = read_dataset(paths, "trade_calendar", start_date=start_date, end_date=end_date)
    if not local_calendar.empty and {"trade_date", "is_open"} <= set(local_calendar.columns):
        return _open_trade_dates_from_frame(local_calendar)

    if not plan_only:
        remote_calendar = provider.get_trade_calendar(start_date=start_date, end_date=end_date)
        if not remote_calendar.empty:
            return _open_trade_dates_from_frame(remote_calendar)

    return [
        current_day
        for current_day in pd.date_range(start_date, end_date, freq="B").date.tolist()
        if current_day.weekday() < 5
    ]


def chunk_trade_dates(trade_dates: Sequence[date], chunk_size: int) -> list[list[date]]:
    if chunk_size <= 0:
        raise TushareConfigurationError("minute_chunk_days must be a positive integer")
    if not trade_dates:
        return []

    chunks: list[list[date]] = []
    current: list[date] = []
    for trade_day in trade_dates:
        current.append(trade_day)
        if len(current) >= chunk_size:
            chunks.append(current)
            current = []
    if current:
        chunks.append(current)
    return chunks


def scan_minute_bar_gaps(
    paths: AppPaths,
    trade_dates: Sequence[date | str],
    expected_symbols: Sequence[str],
) -> GapScanResult:
    normalized_trade_dates = [pd.Timestamp(value).date() for value in trade_dates]
    normalized_symbols = restrict_stock_symbols(expected_symbols)
    frame = read_dataset(
        paths=paths,
        dataset_name="minute_bars",
        start_date=normalized_trade_dates[0],
        end_date=normalized_trade_dates[-1],
        symbols=normalized_symbols,
    )

    counts: dict[tuple[str, str], int] = {}
    if not frame.empty:
        grouped = (
            frame.groupby(["trade_date", "symbol"])
            .size()
            .reset_index(name="bar_count")
        )
        counts = {
            (pd.Timestamp(row.trade_date).date().isoformat(), str(row.symbol)): int(row.bar_count)
            for row in grouped.itertuples(index=False)
        }

    issues: list[GapIssue] = []
    affected_dates: set[str] = set()
    for trade_day in normalized_trade_dates:
        trade_day_key = trade_day.isoformat()
        for symbol in normalized_symbols:
            actual = counts.get((trade_day_key, symbol), 0)
            if actual == EXPECTED_BARS_PER_DAY:
                continue
            issues.append(GapIssue(trade_date=trade_day_key, symbol=symbol, actual_bars=actual))
            affected_dates.add(trade_day_key)

    return GapScanResult(
        expected_trade_dates=tuple(day.isoformat() for day in normalized_trade_dates),
        expected_symbol_count=len(normalized_symbols),
        issue_count=len(issues),
        affected_trade_dates=tuple(sorted(affected_dates)),
        issues=tuple(issues),
    )


def validate_minute_data(
    paths: AppPaths,
    start_date: date | str | None = None,
    end_date: date | str | None = None,
    symbols: Sequence[str] | None = None,
) -> dict[str, object]:
    frame = read_dataset(
        paths=paths,
        dataset_name="minute_bars",
        start_date=start_date,
        end_date=end_date,
        symbols=restrict_stock_symbols(symbols) if symbols else None,
    )
    reference_frames = {
        dataset_name: read_dataset(paths, dataset_name, start_date=start_date, end_date=end_date, symbols=symbols)
        for dataset_name in ("security_master", "suspensions")
    }
    results = run_quality_checks("minute_bars", frame, reference_frames=reference_frames)
    return {
        "row_count": len(frame.index),
        "validation_results": [quality_check_to_dict(result) for result in results],
        "failed_error_checks": [
            quality_check_to_dict(result)
            for result in results
            if result.severity == "error" and result.status == "failed"
        ],
    }


def rebuild_dataset_partitions(
    paths: AppPaths,
    dataset_name: str,
    start_date: date | str | None = None,
    end_date: date | str | None = None,
) -> dict[str, object]:
    ensure_state_dirs(paths)
    frame = read_dataset(paths, dataset_name, start_date=start_date, end_date=end_date)
    ingestion_run_id = start_ingestion_run(
        registry_path=paths.registry_path,
        provider_name="maintenance_rebuild",
        notes=f"rebuild_partitions:{dataset_name}",
    )
    try:
        if dataset_name == "minute_bars":
            validation_results = run_quality_checks(
                dataset_name,
                frame,
                reference_frames={
                    "security_master": read_dataset(paths, "security_master"),
                    "suspensions": read_dataset(paths, "suspensions", start_date=start_date, end_date=end_date),
                },
            )
            record_validation_results(paths.registry_path, validation_results)
            failed_errors = [
                result
                for result in validation_results
                if result.severity == "error" and result.status == "failed"
            ]
            if failed_errors:
                details = "; ".join(f"{result.check_name}: {result.details}" for result in failed_errors)
                raise ValueError(f"cannot rebuild invalid minute_bars dataset: {details}")

        files = write_dataset(paths=paths, dataset_name=dataset_name, frame=frame)
        record_file_manifest(paths.registry_path, files)
        finish_ingestion_run(paths.registry_path, ingestion_run_id, status="completed")
    except Exception:
        finish_ingestion_run(paths.registry_path, ingestion_run_id, status="failed")
        raise

    return {
        "dataset_name": dataset_name,
        "row_count": len(frame.index),
        "file_count": len(files),
    }


def quality_check_to_dict(result: QualityCheckResult) -> dict[str, object]:
    return {
        "dataset_name": result.dataset_name,
        "check_name": result.check_name,
        "severity": result.severity,
        "status": result.status,
        "details": result.details,
        "validation_run_id": result.validation_run_id,
    }


def sync_plan_to_dict(plan: SyncPlan) -> dict[str, object]:
    payload = asdict(plan)
    if plan.gap_scan is not None:
        payload["gap_scan"] = {
            **asdict(plan.gap_scan),
            "issues": [asdict(issue) for issue in plan.gap_scan.issues],
        }
    return payload


def sync_run_summary_to_dict(summary: SyncRunSummary) -> dict[str, object]:
    payload = asdict(summary)
    if summary.gap_scan is not None:
        payload["gap_scan"] = {
            **asdict(summary.gap_scan),
            "issues": [asdict(issue) for issue in summary.gap_scan.issues],
        }
    return payload


def json_dump(data: object) -> str:
    return json.dumps(data, indent=2, sort_keys=True, default=str)


def _open_trade_dates_from_frame(frame: pd.DataFrame) -> list[date]:
    result = frame.copy()
    result["trade_date"] = pd.to_datetime(result["trade_date"]).dt.date
    return sorted(day for day in result.loc[result["is_open"].astype(int) == 1, "trade_date"].tolist())
