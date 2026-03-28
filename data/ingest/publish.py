from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Mapping, Sequence

import pandas as pd

from data.providers.base import SUPPORTED_DATASETS, DataProvider, ProviderCapabilities
from data.providers.local_bundle import canonicalize_symbol, infer_exchange
from data.quality.checks import QualityCheckResult, run_quality_checks
from data.store.duckdb_registry import (
    finish_ingestion_run,
    record_file_manifest,
    record_provider_capabilities,
    record_validation_results,
    start_ingestion_run,
)
from data.store.parquet_store import WrittenFile, write_dataset
from quantlab.config import AppPaths
from quantlab.storage import ensure_state_dirs

ASIA_SHANGHAI = "Asia/Shanghai"


@dataclass(frozen=True)
class PublishResult:
    ingestion_run_id: str
    datasets: dict[str, int]
    files: list[WrittenFile]
    validation_results: list[QualityCheckResult]


def publish_from_provider(
    provider: DataProvider,
    paths: AppPaths,
    dataset_names: Sequence[str] | None = None,
    start_date: date | str | None = None,
    end_date: date | str | None = None,
    symbols: Sequence[str] | None = None,
    notes: str | None = None,
) -> PublishResult:
    ensure_state_dirs(paths)
    record_provider_capabilities(paths.registry_path, provider.name, provider.capabilities())

    selected_datasets = tuple(dataset_names or SUPPORTED_DATASETS)
    ingestion_run_id = start_ingestion_run(
        registry_path=paths.registry_path,
        provider_name=provider.name,
        notes=notes,
    )

    raw_frames = _fetch_provider_frames(
        provider=provider,
        dataset_names=selected_datasets,
        start_date=start_date,
        end_date=end_date,
        symbols=symbols,
    )
    normalized_frames = {
        dataset_name: normalize_dataset_frame(dataset_name, frame)
        for dataset_name, frame in raw_frames.items()
    }

    validation_results: list[QualityCheckResult] = []
    written_files: list[WrittenFile] = []
    row_counts: dict[str, int] = {}

    try:
        for dataset_name in selected_datasets:
            frame = normalized_frames[dataset_name]
            dataset_results = run_quality_checks(
                dataset_name=dataset_name,
                frame=frame,
                reference_frames=normalized_frames,
            )
            validation_results.extend(dataset_results)
            record_validation_results(paths.registry_path, dataset_results)

            failed_checks = [
                result
                for result in dataset_results
                if result.status == "failed" and result.severity == "error"
            ]
            if failed_checks:
                details = "; ".join(f"{result.check_name}: {result.details}" for result in failed_checks)
                raise ValueError(f"quality checks failed for {dataset_name}: {details}")

            files = write_dataset(paths=paths, dataset_name=dataset_name, frame=frame)
            written_files.extend(files)
            row_counts[dataset_name] = len(frame.index)
            record_file_manifest(paths.registry_path, files)

    except Exception:
        finish_ingestion_run(
            registry_path=paths.registry_path,
            ingestion_run_id=ingestion_run_id,
            status="failed",
        )
        raise

    finish_ingestion_run(
        registry_path=paths.registry_path,
        ingestion_run_id=ingestion_run_id,
        status="completed",
    )
    return PublishResult(
        ingestion_run_id=ingestion_run_id,
        datasets=row_counts,
        files=written_files,
        validation_results=validation_results,
    )


def publish_minute_bars(
    paths: AppPaths,
    records: Sequence[object],
    provider_name: str = "local_bundle",
) -> PublishResult:
    frame = pd.DataFrame(
        [
            record.model_dump(mode="json") if hasattr(record, "model_dump") else dict(record)
            for record in records
        ]
    )
    return _publish_records_dataset(
        paths=paths,
        dataset_name="minute_bars",
        frame=frame,
        provider_name=provider_name,
    )


def publish_security_status_history(
    paths: AppPaths,
    records: Sequence[object],
    provider_name: str = "local_bundle",
) -> PublishResult:
    frame = pd.DataFrame(
        [
            record.model_dump(mode="json") if hasattr(record, "model_dump") else dict(record)
            for record in records
        ]
    )
    return _publish_records_dataset(
        paths=paths,
        dataset_name="security_status_history",
        frame=frame,
        provider_name=provider_name,
    )


def normalize_dataset_frame(dataset_name: str, frame: pd.DataFrame) -> pd.DataFrame:
    if dataset_name not in SUPPORTED_DATASETS:
        raise ValueError(f"unsupported dataset: {dataset_name}")

    if frame is None or frame.empty:
        return pd.DataFrame(columns=_dataset_columns(dataset_name))

    result = frame.copy()

    if "symbol" in result.columns:
        result["symbol"] = result["symbol"].map(canonicalize_symbol)

    if dataset_name == "minute_bars":
        return _normalize_minute_bars(result)
    if dataset_name == "security_master":
        return _normalize_security_master(result)
    if dataset_name == "security_status_history":
        return _normalize_security_status_history(result)
    if dataset_name == "trade_calendar":
        return _normalize_trade_calendar(result)
    if dataset_name == "adjustment_factors":
        return _normalize_adjustment_factors(result)
    if dataset_name == "suspensions":
        return _normalize_suspensions(result)
    if dataset_name == "price_limits":
        return _normalize_price_limits(result)

    raise AssertionError(f"missing normalizer for {dataset_name}")


def _fetch_provider_frames(
    provider: DataProvider,
    dataset_names: Sequence[str],
    start_date: date | str | None,
    end_date: date | str | None,
    symbols: Sequence[str] | None,
) -> dict[str, pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {}
    for dataset_name in dataset_names:
        if dataset_name == "minute_bars":
            frames[dataset_name] = provider.get_minute_bars(start_date=start_date, end_date=end_date, symbols=symbols)
        elif dataset_name == "security_master":
            frames[dataset_name] = provider.get_security_master()
        elif dataset_name == "security_status_history":
            frames[dataset_name] = provider.get_security_status_history(
                start_date=start_date,
                end_date=end_date,
                symbols=symbols,
            )
        elif dataset_name == "trade_calendar":
            frames[dataset_name] = provider.get_trade_calendar(start_date=start_date, end_date=end_date)
        elif dataset_name == "adjustment_factors":
            frames[dataset_name] = provider.get_adjustment_factors(
                start_date=start_date,
                end_date=end_date,
                symbols=symbols,
            )
        elif dataset_name == "suspensions":
            frames[dataset_name] = provider.get_suspensions(
                start_date=start_date,
                end_date=end_date,
                symbols=symbols,
            )
        elif dataset_name == "price_limits":
            frames[dataset_name] = provider.get_price_limits(
                start_date=start_date,
                end_date=end_date,
                symbols=symbols,
            )
        else:
            raise ValueError(f"unsupported dataset: {dataset_name}")

    return frames


def _publish_records_dataset(
    paths: AppPaths,
    dataset_name: str,
    frame: pd.DataFrame,
    provider_name: str,
) -> PublishResult:
    ensure_state_dirs(paths)
    ingestion_run_id = start_ingestion_run(
        registry_path=paths.registry_path,
        provider_name=provider_name,
        notes=f"direct_publish:{dataset_name}",
    )
    record_provider_capabilities(
        paths.registry_path,
        provider_name,
        ProviderCapabilities(
            supports_minute_bars=dataset_name == "minute_bars",
            supports_security_status_history=dataset_name == "security_status_history",
            supports_price_limits=dataset_name == "price_limits",
            supports_suspensions=dataset_name == "suspensions",
        ),
    )
    normalized = normalize_dataset_frame(dataset_name, frame)
    validation_results = run_quality_checks(dataset_name=dataset_name, frame=normalized, reference_frames={})
    record_validation_results(paths.registry_path, validation_results)
    failed_checks = [
        result
        for result in validation_results
        if result.status == "failed" and result.severity == "error"
        and result.check_name not in {"valid_session_times"}
    ]
    if failed_checks:
        finish_ingestion_run(
            registry_path=paths.registry_path,
            ingestion_run_id=ingestion_run_id,
            status="failed",
        )
        details = "; ".join(f"{result.check_name}: {result.details}" for result in failed_checks)
        raise ValueError(f"quality checks failed for {dataset_name}: {details}")

    files = write_dataset(paths=paths, dataset_name=dataset_name, frame=normalized)
    record_file_manifest(paths.registry_path, files)
    finish_ingestion_run(
        registry_path=paths.registry_path,
        ingestion_run_id=ingestion_run_id,
        status="completed",
    )
    return PublishResult(
        ingestion_run_id=ingestion_run_id,
        datasets={dataset_name: len(normalized.index)},
        files=files,
        validation_results=validation_results,
    )


def _normalize_minute_bars(frame: pd.DataFrame) -> pd.DataFrame:
    required_columns = (
        "symbol",
        "bar_start_ts",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
    )
    _require_columns(frame, required_columns)

    result = frame.copy()
    result["bar_start_ts"] = _normalize_timestamp_series(result["bar_start_ts"])
    if "bar_end_ts" in result.columns:
        result["bar_end_ts"] = _normalize_timestamp_series(result["bar_end_ts"])
    else:
        result["bar_end_ts"] = result["bar_start_ts"] + pd.Timedelta(minutes=1)

    result["trade_date"] = result["bar_start_ts"].dt.date
    if "exchange" not in result.columns:
        result["exchange"] = result["symbol"].map(infer_exchange)
    else:
        result["exchange"] = result["exchange"].fillna("").replace("", pd.NA)
        result["exchange"] = result["exchange"].fillna(result["symbol"].map(infer_exchange))

    if "is_synthetic_bar" not in result.columns:
        result["is_synthetic_bar"] = False

    for optional_column in ("pre_close", "vwap"):
        if optional_column not in result.columns:
            result[optional_column] = pd.NA

    ordered = result[_dataset_columns("minute_bars")]
    return ordered.sort_values(["symbol", "bar_start_ts"]).reset_index(drop=True)


def _normalize_security_master(frame: pd.DataFrame) -> pd.DataFrame:
    required_columns = ("symbol", "list_date", "board", "name", "is_st")
    _require_columns(frame, required_columns)

    result = frame.copy()
    if "exchange" not in result.columns:
        result["exchange"] = result["symbol"].map(infer_exchange)
    result["list_date"] = pd.to_datetime(result["list_date"]).dt.date
    if "delist_date" not in result.columns:
        result["delist_date"] = pd.NaT
    else:
        result["delist_date"] = pd.to_datetime(result["delist_date"], errors="coerce").dt.date

    return result[_dataset_columns("security_master")].sort_values(["symbol"]).reset_index(drop=True)


def _normalize_security_status_history(frame: pd.DataFrame) -> pd.DataFrame:
    required_columns = ("symbol", "effective_from", "name", "is_st", "status_reason")
    _require_columns(frame, required_columns)

    result = frame.copy()
    result["effective_from"] = pd.to_datetime(result["effective_from"]).dt.date
    if "effective_to" not in result.columns:
        result["effective_to"] = pd.NaT
    else:
        result["effective_to"] = pd.to_datetime(result["effective_to"], errors="coerce").dt.date

    return result[_dataset_columns("security_status_history")].sort_values(
        ["symbol", "effective_from"]
    ).reset_index(drop=True)


def _normalize_trade_calendar(frame: pd.DataFrame) -> pd.DataFrame:
    required_columns = ("trade_date", "is_open")
    _require_columns(frame, required_columns)

    result = frame.copy()
    result["trade_date"] = pd.to_datetime(result["trade_date"]).dt.date
    for optional_column in ("prev_trade_date", "next_trade_date"):
        if optional_column not in result.columns:
            result[optional_column] = pd.NaT
        result[optional_column] = pd.to_datetime(result[optional_column], errors="coerce").dt.date

    return result[_dataset_columns("trade_calendar")].sort_values(["trade_date"]).reset_index(drop=True)


def _normalize_adjustment_factors(frame: pd.DataFrame) -> pd.DataFrame:
    required_columns = ("symbol", "ex_date", "adj_factor", "action_type")
    _require_columns(frame, required_columns)

    result = frame.copy()
    result["ex_date"] = pd.to_datetime(result["ex_date"]).dt.date
    return result[_dataset_columns("adjustment_factors")].sort_values(["symbol", "ex_date"]).reset_index(drop=True)


def _normalize_suspensions(frame: pd.DataFrame) -> pd.DataFrame:
    required_columns = ("symbol", "trade_date", "is_suspended")
    _require_columns(frame, required_columns)

    result = frame.copy()
    result["trade_date"] = pd.to_datetime(result["trade_date"]).dt.date
    return result[_dataset_columns("suspensions")].sort_values(["symbol", "trade_date"]).reset_index(drop=True)


def _normalize_price_limits(frame: pd.DataFrame) -> pd.DataFrame:
    required_columns = ("symbol", "trade_date", "pre_close", "up_limit", "down_limit")
    _require_columns(frame, required_columns)

    result = frame.copy()
    result["trade_date"] = pd.to_datetime(result["trade_date"]).dt.date
    return result[_dataset_columns("price_limits")].sort_values(["symbol", "trade_date"]).reset_index(drop=True)


def _normalize_timestamp_series(values: pd.Series) -> pd.Series:
    timestamps = pd.to_datetime(values)
    if timestamps.dt.tz is None:
        return timestamps.dt.tz_localize(ASIA_SHANGHAI)
    return timestamps.dt.tz_convert(ASIA_SHANGHAI)


def _require_columns(frame: pd.DataFrame, columns: Sequence[str]) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise ValueError(f"missing required columns: {missing}")


def _dataset_columns(dataset_name: str) -> list[str]:
    columns: Mapping[str, list[str]] = {
        "minute_bars": [
            "symbol",
            "exchange",
            "trade_date",
            "bar_start_ts",
            "bar_end_ts",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "amount",
            "pre_close",
            "vwap",
            "is_synthetic_bar",
        ],
        "security_master": [
            "symbol",
            "exchange",
            "list_date",
            "delist_date",
            "board",
            "name",
            "is_st",
        ],
        "security_status_history": [
            "symbol",
            "effective_from",
            "effective_to",
            "name",
            "is_st",
            "status_reason",
        ],
        "trade_calendar": [
            "trade_date",
            "is_open",
            "prev_trade_date",
            "next_trade_date",
        ],
        "adjustment_factors": [
            "symbol",
            "ex_date",
            "adj_factor",
            "action_type",
        ],
        "suspensions": [
            "symbol",
            "trade_date",
            "is_suspended",
        ],
        "price_limits": [
            "symbol",
            "trade_date",
            "pre_close",
            "up_limit",
            "down_limit",
        ],
    }
    return columns[dataset_name]
