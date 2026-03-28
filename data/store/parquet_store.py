from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Sequence

import pandas as pd

from quantlab.config import AppPaths
from quantlab.storage import dataset_root


@dataclass(frozen=True)
class WrittenFile:
    dataset_name: str
    partition_key: str
    file_path: str
    row_count: int
    content_hash: str


def write_dataset(paths: AppPaths, dataset_name: str, frame: pd.DataFrame) -> list[WrittenFile]:
    root = dataset_root(paths, dataset_name)
    root.mkdir(parents=True, exist_ok=True)

    if frame.empty:
        return []

    partition_column = _partition_column(dataset_name, frame)
    sort_columns = _sort_columns(dataset_name, frame)
    ordered = frame.sort_values(sort_columns).reset_index(drop=True) if sort_columns else frame.reset_index(drop=True)

    if partition_column is None:
        file_path = root / "part-0000.parquet"
        ordered.to_parquet(file_path, compression="zstd", index=False)
        return [
            WrittenFile(
                dataset_name=dataset_name,
                partition_key="__default__",
                file_path=str(file_path),
                row_count=len(ordered.index),
                content_hash=_file_hash(file_path),
            )
        ]

    written_files: list[WrittenFile] = []
    normalized_partition = ordered.assign(_partition_value=ordered[partition_column].map(_partition_value))
    for partition_value, partition_frame in normalized_partition.groupby("_partition_value", sort=True):
        partition_dir = root / f"{partition_column}={partition_value}"
        if partition_dir.exists():
            shutil.rmtree(partition_dir)
        partition_dir.mkdir(parents=True, exist_ok=True)

        file_path = partition_dir / "part-0000.parquet"
        to_write = partition_frame.drop(columns=["_partition_value"])
        to_write.to_parquet(file_path, compression="zstd", index=False)
        written_files.append(
            WrittenFile(
                dataset_name=dataset_name,
                partition_key=str(partition_value),
                file_path=str(file_path),
                row_count=len(to_write.index),
                content_hash=_file_hash(file_path),
            )
        )

    return written_files


def read_dataset(
    paths: AppPaths,
    dataset_name: str,
    start_date: date | str | None = None,
    end_date: date | str | None = None,
    symbols: Sequence[str] | None = None,
) -> pd.DataFrame:
    root = dataset_root(paths, dataset_name)
    if not root.exists():
        return pd.DataFrame()

    parquet_files = sorted(root.glob("**/*.parquet"))
    if not parquet_files:
        return pd.DataFrame()

    frame = pd.concat((pd.read_parquet(path) for path in parquet_files), ignore_index=True)
    if frame.empty:
        return frame

    if start_date is not None or end_date is not None:
        date_column = _date_filter_column(dataset_name, frame)
        if date_column is not None:
            frame[date_column] = pd.to_datetime(frame[date_column]).dt.date
            if start_date is not None:
                frame = frame[frame[date_column] >= pd.Timestamp(start_date).date()]
            if end_date is not None:
                frame = frame[frame[date_column] <= pd.Timestamp(end_date).date()]

    if symbols and "symbol" in frame.columns:
        symbol_set = {str(symbol) for symbol in symbols}
        frame = frame[frame["symbol"].astype(str).isin(symbol_set)]

    sort_columns = _sort_columns(dataset_name, frame)
    if sort_columns:
        frame = frame.sort_values(sort_columns)
    return frame.reset_index(drop=True)


def _partition_column(dataset_name: str, frame: pd.DataFrame) -> str | None:
    if "trade_date" in frame.columns:
        return "trade_date"
    return None


def _sort_columns(dataset_name: str, frame: pd.DataFrame) -> list[str]:
    candidates: dict[str, list[str]] = {
        "minute_bars": ["symbol", "bar_start_ts"],
        "security_master": ["symbol"],
        "security_status_history": ["symbol", "effective_from"],
        "trade_calendar": ["trade_date"],
        "adjustment_factors": ["symbol", "ex_date"],
        "suspensions": ["symbol", "trade_date"],
        "price_limits": ["symbol", "trade_date"],
    }
    return [column for column in candidates.get(dataset_name, []) if column in frame.columns]


def _date_filter_column(dataset_name: str, frame: pd.DataFrame) -> str | None:
    for column in ("trade_date", "effective_from", "ex_date", "list_date"):
        if column in frame.columns:
            return column
    return None


def _partition_value(value: object) -> str:
    if isinstance(value, date):
        return value.isoformat()
    if pd.isna(value):
        return "null"
    return str(pd.Timestamp(value).date())


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
