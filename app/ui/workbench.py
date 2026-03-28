from __future__ import annotations

import importlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from backtest.core.engine import run_backtest
from quantlab.config import AppPaths
from quantlab.schemas import BacktestRunConfig, RunArtifactManifest
from reports import ScanBatchResult, persist_backtest_result
from scripts.seed_demo_data import seed_demo_data


SCAN_RUNNER_CANDIDATES: tuple[tuple[str, str], ...] = (
    ("reports", "run_parameter_scan"),
    ("reports.scans", "run_parameter_scan"),
    ("backtest.scan", "run_parameter_scan"),
    ("backtest.scans", "run_parameter_scan"),
    ("reports.scan_runner", "run_parameter_scan"),
    ("scripts.run_parameter_scan", "run_parameter_scan"),
)


@dataclass(slots=True)
class BacktestExecutionResult:
    success: bool
    run_id: str
    message: str
    paths: AppPaths
    manifest: RunArtifactManifest | None = None
    metrics: dict[str, Any] | None = None
    used_seed_demo: bool = False


@dataclass(slots=True)
class ScanRunnerProbe:
    available: bool
    message: str
    runner_name: str | None = None
    runner: Callable[..., Any] | None = None


@dataclass(slots=True)
class ParameterScanExecutionResult:
    success: bool
    message: str
    paths: AppPaths
    batch: ScanBatchResult | None = None
    used_seed_demo: bool = False


def repo_root(root: Path | None = None) -> Path:
    return (root or Path(__file__).resolve().parents[2]).resolve()


def app_root(root: Path | None = None) -> Path:
    return repo_root(root) / "app"


def build_shared_paths(root: Path | None = None) -> AppPaths:
    return AppPaths.from_workspace(repo_root(root))


def build_app_paths(root: Path | None = None) -> AppPaths:
    root_path = repo_root(root)
    state_dir = app_root(root) / ".quantlab"
    return AppPaths(
        workspace_root=root_path,
        local_state_dir=state_dir,
        lake_root=state_dir / "lake",
        registry_path=state_dir / "registry.duckdb",
        runs_root=state_dir / "runs",
    )


def build_execution_paths(root: Path | None = None) -> AppPaths:
    app_paths = build_app_paths(root)
    shared_paths = build_shared_paths(root)
    lake_root = shared_paths.lake_root if _has_market_data(shared_paths) else app_paths.lake_root
    return AppPaths(
        workspace_root=app_paths.workspace_root,
        local_state_dir=app_paths.local_state_dir,
        lake_root=lake_root,
        registry_path=app_paths.registry_path,
        runs_root=app_paths.runs_root,
    )


def seed_app_demo_data(root: Path | None = None) -> AppPaths:
    paths = build_app_paths(root)
    seed_demo_data(paths)
    return paths


def execute_backtest_run(
    config: BacktestRunConfig,
    root: Path | None = None,
    *,
    seed_demo_if_missing: bool = False,
) -> BacktestExecutionResult:
    paths = build_execution_paths(root)
    used_seed_demo = False
    if not _has_market_data(paths):
        if not seed_demo_if_missing:
            return BacktestExecutionResult(
                success=False,
                run_id=config.run_id,
                message=(
                    "No minute-bar dataset is available for execution yet. "
                    "Enable demo seeding or publish data before running."
                ),
                paths=paths,
            )
        seed_app_demo_data(root)
        paths = build_execution_paths(root)
        used_seed_demo = True

    run_config = config.model_copy(update={"run_id": uuid4().hex})
    try:
        result = run_backtest(paths, run_config)
        manifest = persist_backtest_result(paths, result)
    except Exception as exc:
        return BacktestExecutionResult(
            success=False,
            run_id=run_config.run_id,
            message=f"Backtest execution failed: {exc}",
            paths=paths,
            used_seed_demo=used_seed_demo,
        )

    return BacktestExecutionResult(
        success=True,
        run_id=result.run_id,
        message="Backtest completed and artifacts were persisted under app-local state.",
        paths=paths,
        manifest=manifest,
        metrics=result.metrics.model_dump(mode="json"),
        used_seed_demo=used_seed_demo,
    )


def detect_scan_runner() -> ScanRunnerProbe:
    for module_name, function_name in SCAN_RUNNER_CANDIDATES:
        try:
            module = importlib.import_module(module_name)
        except Exception:
            continue
        runner = getattr(module, function_name, None)
        if callable(runner):
            return ScanRunnerProbe(
                available=True,
                message=f"Detected parameter scan hook: {module_name}.{function_name}",
                runner_name=f"{module_name}.{function_name}",
                runner=runner,
            )
    return ScanRunnerProbe(
        available=False,
        message="No parameter scan runner hook is available yet. Browsing saved scan batches still works.",
    )


def execute_parameter_scan(
    request: dict[str, Any],
    root: Path | None = None,
    *,
    seed_demo_if_missing: bool = False,
) -> ParameterScanExecutionResult:
    paths = build_execution_paths(root)
    probe = detect_scan_runner()
    if not probe.available or probe.runner is None:
        return ParameterScanExecutionResult(
            success=False,
            message=probe.message,
            paths=paths,
        )

    used_seed_demo = False
    if not _has_market_data(paths) and seed_demo_if_missing:
        seed_app_demo_data(root)
        paths = build_execution_paths(root)
        used_seed_demo = True

    if not _has_market_data(paths):
        return ParameterScanExecutionResult(
            success=False,
            message=(
                "No minute-bar dataset is available for scan execution yet. "
                "Seed demo data or publish data before running."
            ),
            paths=paths,
            used_seed_demo=used_seed_demo,
        )

    runner = probe.runner
    attempts: tuple[Callable[[], Any], ...] = (
        lambda: runner(paths, request),
        lambda: runner(request, paths),
        lambda: runner(paths=paths, request=request),
        lambda: runner(request=request, paths=paths),
    )
    last_error: Exception | None = None
    for attempt in attempts:
        try:
            payload = attempt()
            batch = _coerce_scan_batch_result(payload)
            return ParameterScanExecutionResult(
                success=True,
                message=f"Parameter scan batch `{batch.scan_batch_id}` completed.",
                paths=paths,
                batch=batch,
                used_seed_demo=used_seed_demo,
            )
        except TypeError as exc:
            last_error = exc
            continue
        except Exception as exc:
            return ParameterScanExecutionResult(
                success=False,
                message=f"Parameter scan execution failed: {exc}",
                paths=paths,
                used_seed_demo=used_seed_demo,
            )

    return ParameterScanExecutionResult(
        success=False,
        message=f"Parameter scan hook signature is unsupported: {last_error}",
        paths=paths,
        used_seed_demo=used_seed_demo,
    )


def _coerce_scan_batch_result(payload: Any) -> ScanBatchResult:
    if isinstance(payload, ScanBatchResult):
        return payload
    if isinstance(payload, dict):
        return ScanBatchResult.model_validate(payload)
    raise TypeError(f"Unsupported parameter scan payload type: {type(payload)!r}")


def _has_market_data(paths: AppPaths) -> bool:
    minute_root = paths.lake_root / "minute_bars"
    if not minute_root.exists():
        return False
    return any(minute_root.rglob("*.parquet"))
