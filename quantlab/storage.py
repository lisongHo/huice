from __future__ import annotations

from pathlib import Path

from quantlab.config import AppPaths

ARTIFACT_FILE_NAMES = {
    "manifest": "manifest.json",
    "config": "config.json",
    "metrics": "metrics.json",
    "equity_curve": "equity_curve.parquet",
    "drawdown_curve": "drawdown_curve.parquet",
    "trades": "trades.parquet",
    "annual_returns": "annual_returns.parquet",
}


def ensure_state_dirs(paths: AppPaths) -> None:
    for directory in (
        paths.local_state_dir,
        paths.lake_root,
        paths.lake_root / "minute_bars",
        readiness_root(paths),
        sync_runs_root(paths),
        paths.runs_root,
    ):
        directory.mkdir(parents=True, exist_ok=True)


def dataset_root(paths: AppPaths, dataset_name: str) -> Path:
    return paths.lake_root / dataset_name


def minute_partition_path(paths: AppPaths, trade_date: str) -> Path:
    return dataset_root(paths, "minute_bars") / f"trade_date={trade_date}"


def run_dir(paths: AppPaths, run_id: str) -> Path:
    return paths.runs_root / run_id


def readiness_root(paths: AppPaths) -> Path:
    return paths.local_state_dir / "readiness"


def readiness_artifact_path(paths: AppPaths) -> Path:
    return readiness_root(paths) / "latest.json"


def readiness_snapshot_path(paths: AppPaths, snapshot_name: str) -> Path:
    return readiness_root(paths) / snapshot_name


def sync_runs_root(paths: AppPaths) -> Path:
    return paths.local_state_dir / "sync_runs"


def sync_run_dir(paths: AppPaths, sync_run_id: str) -> Path:
    return sync_runs_root(paths) / sync_run_id
