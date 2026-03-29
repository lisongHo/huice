from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from quantlab.config import AppPaths
from quantlab.registry import bootstrap_registry
from quantlab.schemas import BacktestRunConfig, RunArtifactManifest, RunStatus, SyncArtifactManifest
from quantlab.storage import ARTIFACT_FILE_NAMES, run_dir, sync_run_dir
from quantlab.strategies.builtin import BUILTIN_STRATEGY_NAME, default_strategy_params
from reports import ScanBatchResult

from app.ui.workbench import app_root, build_app_paths, build_shared_paths, repo_root


def workspace_root() -> Path:
    return repo_root()


def get_app_paths(root: Path | None = None) -> AppPaths:
    return build_app_paths(root)


def get_shared_paths(root: Path | None = None) -> AppPaths:
    return build_shared_paths(root)


def get_browse_paths(root: Path | None = None) -> list[tuple[str, AppPaths]]:
    app_paths = get_app_paths(root)
    shared_paths = get_shared_paths(root)
    return [
        ("app", app_paths),
        ("shared", shared_paths),
    ]


def _read_json_file(path: Path) -> dict[str, Any] | list[dict[str, Any]] | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _resolve_path(raw_path: str | Path, root: Path) -> Path:
    path = Path(raw_path)
    return path if path.is_absolute() else root / path


def _read_frame(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    if path.suffix == ".parquet":
        return pd.read_parquet(path)
    if path.suffix == ".csv":
        return pd.read_csv(path)
    if path.suffix == ".json":
        payload = _read_json_file(path)
        if payload is None:
            return pd.DataFrame()
        if isinstance(payload, list):
            return pd.DataFrame(payload)
        return pd.DataFrame([payload])
    return pd.DataFrame()


def _read_artifact_payload(path: Path) -> dict[str, Any] | list[Any] | str | None:
    if not path.exists():
        return None
    suffix = path.suffix.lower()
    if suffix == ".json":
        return _read_json_file(path)
    if suffix == ".csv":
        return _read_frame(path).to_dict(orient="records")
    if suffix == ".parquet":
        return _read_frame(path).to_dict(orient="records")
    return path.read_text(encoding="utf-8")


@dataclass(slots=True)
class TemplateSummary:
    template_name: str
    strategy_name: str
    execution_mode: str
    start_date: str | None
    end_date: str | None
    source: str
    notes: str
    config: BacktestRunConfig | None = None


@dataclass(slots=True)
class RunSummary:
    run_id: str
    strategy_name: str
    start_date: str
    end_date: str
    execution_mode: str
    status: RunStatus | str
    created_at: datetime | None
    completed_at: datetime | None
    artifacts_dir: str
    metrics_path: str | None
    total_return_pct: float | None = None
    max_drawdown_pct: float | None = None
    trade_count: int | None = None
    source_label: str = "app"


@dataclass(slots=True)
class ValidationSummary:
    status_counts: pd.DataFrame
    severity_counts: pd.DataFrame
    recent_results: pd.DataFrame


@dataclass(slots=True)
class ValidationResultItem:
    validation_run_id: str
    dataset_name: str
    check_name: str
    severity: str
    status: str
    details: str


@dataclass(slots=True)
class FileManifestSummary:
    dataset_name: str
    file_count: int
    row_count: int | None


@dataclass(slots=True)
class ProviderCapabilitySummary:
    provider_name: str
    supports_minute_bars: bool
    supports_security_status_history: bool
    supports_price_limits: bool
    supports_suspensions: bool


@dataclass(slots=True)
class DataHealthSnapshot:
    note: str
    validation_summary: ValidationSummary | None
    validation_results: list[ValidationResultItem]
    file_manifest: list[FileManifestSummary]
    provider_capabilities: list[ProviderCapabilitySummary]


@dataclass(slots=True)
class ReadinessSummary:
    status: str
    headline: str
    body: str
    next_steps: list[str]


@dataclass(slots=True)
class ReadinessArtifact:
    path: str
    modified_at: datetime | None
    payload: dict[str, Any] | list[Any] | str
    summary: ReadinessSummary


@dataclass(slots=True)
class ScanBatchSummary:
    scan_batch_id: str
    strategy_name: str
    created_at: datetime | None
    run_count: int
    parameter_names: list[str]
    best_run_id: str | None
    best_return_pct: float | None
    source_label: str
    result_path: str


@dataclass(slots=True)
class SyncRunRecord:
    sync_run_id: str
    workflow: str
    status: RunStatus | str
    requested_at: datetime | None
    completed_at: datetime | None
    summary_path: str
    artifact_dir: str
    source_label: str = "app"


@dataclass(slots=True)
class SyncRunArtifact:
    sync_run_id: str
    workflow: str | None
    status: RunStatus | str | None
    artifact_dir: str
    manifest: SyncArtifactManifest | None
    request_path: str | None
    summary_path: str | None
    validation_path: str | None
    request_payload: dict[str, Any] | list[Any] | str | None
    summary_payload: dict[str, Any] | list[Any] | str | None
    validation_payload: dict[str, Any] | list[Any] | str | None
    source_label: str = "app"


@dataclass(slots=True)
class ExperimentLibraryEntry:
    label: str
    path: str
    kind: str
    modified_at: datetime | None
    item_count: int | None


@dataclass(slots=True)
class HomePageData:
    recent_runs: list[RunSummary]
    validation_results: list[ValidationResultItem]
    validation_summary: ValidationSummary | None
    readiness_summary: ReadinessSummary
    default_template: TemplateSummary
    latest_saved_template: TemplateSummary | None
    data_health_note: str
    app_run_count: int
    shared_run_count: int
    scan_batches: list[ScanBatchSummary]
    experiment_library_entries: list[ExperimentLibraryEntry]
    app_paths: AppPaths
    shared_paths: AppPaths


@dataclass(slots=True)
class RunSubmission:
    config: BacktestRunConfig
    run_requested: bool
    payload: dict[str, Any]
    summary: dict[str, Any]


@dataclass(slots=True)
class RunArtifacts:
    run_id: str
    manifest: RunArtifactManifest | None
    config: BacktestRunConfig | None
    metrics: dict[str, Any] | None
    equity_curve: pd.DataFrame
    drawdown_curve: pd.DataFrame
    trades: pd.DataFrame
    annual_returns: pd.DataFrame
    source_label: str = "app"


def default_template_summary() -> TemplateSummary:
    params = default_strategy_params()
    return TemplateSummary(
        template_name="v0.1 default builtin",
        strategy_name=BUILTIN_STRATEGY_NAME,
        execution_mode="last_5m_vwap",
        start_date=None,
        end_date=None,
        source="builtin defaults",
        notes=(
            "Default single-strategy template for near-close A-share minute research. "
            "Set the date window on the Single Backtest page before launching."
        ),
        config=BacktestRunConfig(
            strategy_name=BUILTIN_STRATEGY_NAME,
            start_date="2022-01-01",
            end_date="2022-01-02",
            strategy_params=params,
        ),
    )


def _readiness_root(paths: AppPaths | None = None, root: Path | None = None) -> Path:
    if paths is not None:
        return paths.local_state_dir / "readiness"
    return get_shared_paths(root).local_state_dir / "readiness"


def _coerce_readiness_summary(payload: dict[str, Any] | list[Any] | str, *, path: Path) -> ReadinessSummary:
    if isinstance(payload, dict):
        candidate = payload
        if isinstance(candidate.get("summary"), dict):
            candidate = candidate["summary"]
        elif isinstance(candidate.get("readiness"), dict):
            candidate = candidate["readiness"]

        endpoint_probes = payload.get("endpoint_probes")
        config = payload.get("config")
        if isinstance(endpoint_probes, list) and isinstance(config, dict):
            token_visible = bool(config.get("token_visible"))
            errors = [item for item in endpoint_probes if isinstance(item, dict) and str(item.get("status", "")).lower() == "error"]
            if not token_visible:
                return ReadinessSummary(
                    status="warning",
                    headline="Provider readiness check cannot see a token yet.",
                    body="The latest saved preflight says the provider token is not visible to this workspace.",
                    next_steps=[
                        "Set TUSHARE_TOKEN or fill configs/provider.toml.",
                        "Run the readiness check again after updating credentials.",
                    ],
                )
            if errors:
                combined_error_text = " ".join(str(item.get("error_message", "")) for item in errors)
                if "minute-data permission is missing" in combined_error_text.lower():
                    return ReadinessSummary(
                        status="warning",
                        headline="Latest provider readiness check found missing minute-data permission.",
                        body="The token is visible, but the saved preflight still cannot access stock minute history.",
                        next_steps=[
                            "Enable the Tushare minute-data permission for this token.",
                            "Run the readiness check again after permissions are updated.",
                        ],
                    )
                if "unable to reach tushare api" in combined_error_text.lower():
                    return ReadinessSummary(
                        status="warning",
                        headline="Latest provider readiness check could not reach the upstream API.",
                        body="The saved preflight shows a network or DNS failure rather than a local configuration issue.",
                        next_steps=[
                            "Retry the readiness check with network access.",
                            "If it still fails, verify the configured API URL and local network path.",
                        ],
                    )
                return ReadinessSummary(
                    status="warning",
                    headline="Latest provider readiness check found upstream access gaps.",
                    body="The token is visible, but one or more required endpoints still returned errors.",
                    next_steps=[
                        "Review the saved endpoint probe errors on the Provider Readiness page.",
                        "Grant the missing Tushare permissions, then rerun the readiness check.",
                    ],
                )
            return ReadinessSummary(
                status="success",
                headline="Latest provider readiness check passed.",
                body="The saved preflight can see the token and the probed endpoints responded successfully.",
                next_steps=[
                    "Run the sync or backfill flow to publish data.",
                    "Open Data Health after the first real publish.",
                ],
            )

        next_steps = candidate.get("next_steps")
        if not isinstance(next_steps, list):
            next_steps = payload.get("next_steps") if isinstance(payload.get("next_steps"), list) else []
        return ReadinessSummary(
            status=str(candidate.get("status", payload.get("status", "info"))),
            headline=str(
                candidate.get(
                    "headline",
                    payload.get("headline", "Latest provider readiness artifact is available."),
                )
            ),
            body=str(
                candidate.get(
                    "body",
                    payload.get("body", f"Loaded persisted readiness data from `{path}`."),
                )
            ),
            next_steps=[str(step) for step in next_steps],
        )

    return ReadinessSummary(
        status="info",
        headline="Latest provider readiness artifact is available.",
        body=f"Loaded persisted readiness data from `{path}`.",
        next_steps=[],
    )


def load_latest_readiness_artifact(
    paths: AppPaths | None = None,
    root: Path | None = None,
) -> ReadinessArtifact | None:
    readiness_root = _readiness_root(paths=paths, root=root)
    if not readiness_root.exists():
        return None

    candidates = [path for path in readiness_root.rglob("*") if path.is_file()]
    if not candidates:
        return None

    latest_path = max(
        candidates,
        key=lambda item: (item.stat().st_mtime, item.as_posix()),
    )
    if latest_path.suffix.lower() == ".json":
        payload = _read_json_file(latest_path)
        if payload is None:
            return None
    elif latest_path.suffix.lower() == ".csv":
        payload = _read_frame(latest_path).to_dict(orient="records")
    elif latest_path.suffix.lower() == ".parquet":
        payload = _read_frame(latest_path).to_dict(orient="records")
    else:
        payload = latest_path.read_text(encoding="utf-8")

    summary = _coerce_readiness_summary(payload, path=latest_path)
    return ReadinessArtifact(
        path=str(latest_path),
        modified_at=datetime.fromtimestamp(latest_path.stat().st_mtime),
        payload=payload,
        summary=summary,
    )


def load_latest_saved_readiness_summary(
    paths: AppPaths | None = None,
    root: Path | None = None,
) -> ReadinessSummary | None:
    artifact = load_latest_readiness_artifact(paths=paths, root=root)
    return None if artifact is None else artifact.summary


def load_latest_saved_template(paths: AppPaths | None = None, root: Path | None = None) -> TemplateSummary | None:
    runs = load_recent_runs(limit=25, paths=paths) if paths is not None else load_recent_runs_catalog(limit=25, root=root)
    for summary in runs:
        if str(summary.status).lower() != "completed":
            continue
        config = (
            load_run_config(summary.run_id, paths=paths)
            if paths is not None
            else load_run_artifacts_from_sources(summary.run_id, root=root).config
        )
        if config is None:
            continue
        return TemplateSummary(
            template_name=f"saved from run {summary.run_id[:8]}",
            strategy_name=config.strategy_name,
            execution_mode=config.execution.mode.value,
            start_date=str(config.start_date),
            end_date=str(config.end_date),
            source=f"latest completed {summary.source_label} run",
            notes="Most recent completed run config that can be reused as a starting point.",
            config=config,
        )
    return None


def load_run_config(run_id: str, paths: AppPaths | None = None) -> BacktestRunConfig | None:
    paths = paths or get_app_paths()
    config_path = run_dir(paths, run_id) / ARTIFACT_FILE_NAMES["config"]
    payload = _read_json_file(config_path)
    if payload is None or not isinstance(payload, dict):
        return None
    return BacktestRunConfig.model_validate(payload)


def load_run_artifacts(run_id: str, paths: AppPaths | None = None) -> RunArtifacts:
    paths = paths or get_app_paths()
    base_dir = run_dir(paths, run_id)
    manifest_path = base_dir / ARTIFACT_FILE_NAMES["manifest"]
    manifest_payload = _read_json_file(manifest_path)
    manifest = (
        RunArtifactManifest.model_validate(manifest_payload)
        if isinstance(manifest_payload, dict)
        else None
    )

    config = load_run_config(run_id, paths=paths)
    metrics_path = base_dir / ARTIFACT_FILE_NAMES["metrics"]
    metrics_payload = _read_json_file(metrics_path)
    metrics = metrics_payload if isinstance(metrics_payload, dict) else None

    return RunArtifacts(
        run_id=run_id,
        manifest=manifest,
        config=config,
        metrics=metrics,
        equity_curve=_read_frame(base_dir / ARTIFACT_FILE_NAMES["equity_curve"]),
        drawdown_curve=_read_frame(base_dir / ARTIFACT_FILE_NAMES["drawdown_curve"]),
        trades=_read_frame(base_dir / ARTIFACT_FILE_NAMES["trades"]),
        annual_returns=_read_frame(base_dir / ARTIFACT_FILE_NAMES["annual_returns"]),
    )


def load_run_artifacts_from_sources(run_id: str, root: Path | None = None) -> RunArtifacts:
    for source_label, paths in get_browse_paths(root):
        base_dir = run_dir(paths, run_id)
        if not base_dir.exists():
            continue
        artifacts = load_run_artifacts(run_id, paths=paths)
        artifacts.source_label = source_label
        return artifacts
    return RunArtifacts(
        run_id=run_id,
        manifest=None,
        config=None,
        metrics=None,
        equity_curve=pd.DataFrame(),
        drawdown_curve=pd.DataFrame(),
        trades=pd.DataFrame(),
        annual_returns=pd.DataFrame(),
        source_label="missing",
    )


def _connect_registry(paths: AppPaths) -> duckdb.DuckDBPyConnection | None:
    if not paths.registry_path.exists():
        return None
    try:
        return duckdb.connect(str(paths.registry_path), read_only=True)
    except duckdb.Error:
        return None


def _registry_frame(sql: str, paths: AppPaths | None = None) -> pd.DataFrame:
    paths = paths or get_app_paths()
    connection = _connect_registry(paths)
    if connection is None:
        return pd.DataFrame()
    try:
        return connection.execute(sql).fetchdf()
    except duckdb.Error:
        return pd.DataFrame()
    finally:
        connection.close()


def load_recent_runs(limit: int = 10, paths: AppPaths | None = None, *, source_label: str = "app") -> list[RunSummary]:
    paths = paths or get_app_paths()
    if not paths.registry_path.exists():
        return []
    bootstrap_registry(paths.registry_path)
    frame = _registry_frame(
        f"""
        select
            run_id,
            strategy_name,
            cast(start_date as varchar) as start_date,
            cast(end_date as varchar) as end_date,
            execution_mode,
            status,
            created_at,
            completed_at,
            artifacts_dir,
            metrics_path
        from backtest_runs
        order by coalesce(completed_at, created_at) desc, created_at desc
        limit {int(limit)}
        """,
        paths=paths,
    )
    if frame.empty:
        return []
    return _run_summaries_from_frame(frame, paths, source_label)


def load_recent_runs_catalog(limit: int = 10, root: Path | None = None) -> list[RunSummary]:
    combined: list[RunSummary] = []
    for source_label, paths in get_browse_paths(root):
        combined.extend(load_recent_runs(limit=limit, paths=paths, source_label=source_label))
    deduped: dict[str, RunSummary] = {}
    for summary in sorted(combined, key=_run_sort_key, reverse=True):
        deduped.setdefault(summary.run_id, summary)
    return list(deduped.values())[:limit]


def load_latest_validation_summary(paths: AppPaths | None = None) -> ValidationSummary | None:
    paths = paths or get_shared_paths()
    if not paths.registry_path.exists():
        return None
    bootstrap_registry(paths.registry_path)
    recent = _registry_frame(
        """
        select
            validation_run_id,
            dataset_name,
            check_name,
            severity,
            status,
            details
        from validation_results
        order by validation_run_id asc, dataset_name asc, check_name asc
        limit 50
        """,
        paths=paths,
    )
    if recent.empty:
        return None
    recent = recent.copy()
    recent["status"] = recent["status"].map(_canonical_validation_status)
    status_counts = (
        recent.groupby("status", dropna=False)
        .size()
        .reset_index(name="count")
        .sort_values("count", ascending=False)
    )
    severity_counts = (
        recent.groupby("severity", dropna=False)
        .size()
        .reset_index(name="count")
        .sort_values("count", ascending=False)
    )
    return ValidationSummary(
        status_counts=status_counts,
        severity_counts=severity_counts,
        recent_results=recent,
    )


def load_data_health_snapshot(root: Path | None = None) -> DataHealthSnapshot:
    paths = get_shared_paths(root)
    validation_summary = load_latest_validation_summary(paths=paths)
    validation_results: list[ValidationResultItem] = []
    if validation_summary is not None:
        for row in validation_summary.recent_results.itertuples(index=False):
            validation_results.append(
                ValidationResultItem(
                    validation_run_id=str(row.validation_run_id),
                    dataset_name=str(row.dataset_name),
                    check_name=str(row.check_name),
                    severity=str(row.severity),
                    status=str(row.status),
                    details=str(row.details),
                )
            )
    return DataHealthSnapshot(
        note=latest_data_health_note(paths=paths),
        validation_summary=validation_summary,
        validation_results=validation_results,
        file_manifest=load_file_manifest_summary(paths=paths),
        provider_capabilities=load_provider_capabilities(paths=paths),
    )


def load_file_manifest_summary(paths: AppPaths | None = None) -> list[FileManifestSummary]:
    frame = _registry_frame(
        """
        select
            dataset_name,
            count(*) as file_count,
            sum(coalesce(row_count, 0)) as row_count
        from file_manifest
        group by dataset_name
        order by dataset_name asc
        """,
        paths=paths or get_shared_paths(),
    )
    return [
        FileManifestSummary(
            dataset_name=str(row.dataset_name),
            file_count=int(row.file_count),
            row_count=_safe_int(row.row_count),
        )
        for row in frame.itertuples(index=False)
    ]


def load_provider_capabilities(paths: AppPaths | None = None) -> list[ProviderCapabilitySummary]:
    frame = _registry_frame(
        """
        select
            provider_name,
            supports_minute_bars,
            supports_security_status_history,
            supports_price_limits,
            supports_suspensions
        from provider_capabilities
        order by provider_name asc
        """,
        paths=paths or get_shared_paths(),
    )
    return [
        ProviderCapabilitySummary(
            provider_name=str(row.provider_name),
            supports_minute_bars=bool(row.supports_minute_bars),
            supports_security_status_history=bool(row.supports_security_status_history),
            supports_price_limits=bool(row.supports_price_limits),
            supports_suspensions=bool(row.supports_suspensions),
        )
        for row in frame.itertuples(index=False)
    ]


def load_scan_batches(limit: int = 25, root: Path | None = None) -> list[ScanBatchSummary]:
    summaries: list[ScanBatchSummary] = []
    for source_label, paths in get_browse_paths(root):
        if not paths.registry_path.exists():
            continue
        bootstrap_registry(paths.registry_path)
        frame = _registry_frame(
            f"""
            select
                scan_batch_id,
                strategy_name,
                created_at,
                result_path
            from scan_batches
            order by created_at desc
            limit {int(limit)}
            """,
            paths=paths,
        )
        for row in frame.itertuples(index=False):
            batch = _read_scan_batch_result(_resolve_path(str(row.result_path), paths.workspace_root))
            if batch is None:
                continue
            best_run = max(batch.runs, key=lambda item: item.total_return_pct, default=None)
            parameter_names = sorted({name for run in batch.runs for name in run.params})
            summaries.append(
                ScanBatchSummary(
                    scan_batch_id=batch.scan_batch_id,
                    strategy_name=batch.strategy_name,
                    created_at=_as_datetime(row.created_at),
                    run_count=len(batch.runs),
                    parameter_names=parameter_names,
                    best_run_id=best_run.run_id if best_run is not None else None,
                    best_return_pct=best_run.total_return_pct if best_run is not None else None,
                    source_label=source_label,
                    result_path=str(row.result_path),
                )
            )
    summaries.sort(key=lambda item: item.created_at or datetime.min, reverse=True)
    return summaries[:limit]


def load_scan_batch_result_from_sources(scan_batch_id: str, root: Path | None = None) -> ScanBatchResult | None:
    for source_label, paths in get_browse_paths(root):
        if not paths.registry_path.exists():
            continue
        frame = _registry_frame(
            """
            select result_path
            from scan_batches
            where scan_batch_id = ?
            """.replace("?", f"'{scan_batch_id}'"),
            paths=paths,
        )
        if frame.empty:
            continue
        result_path = _resolve_path(str(frame.iloc[0]["result_path"]), paths.workspace_root)
        batch = _read_scan_batch_result(result_path)
        if batch is not None:
            return batch
    return None


def load_recent_sync_runs(limit: int = 25, root: Path | None = None) -> list[SyncRunRecord]:
    summaries: list[SyncRunRecord] = []
    for source_label, paths in get_browse_paths(root):
        if not paths.registry_path.exists():
            continue
        bootstrap_registry(paths.registry_path)
        frame = _registry_frame(
            f"""
            select
                sync_run_id,
                workflow,
                status,
                requested_at,
                completed_at,
                summary_path,
                artifact_dir
            from sync_runs
            order by coalesce(completed_at, requested_at) desc, requested_at desc
            limit {int(limit)}
            """,
            paths=paths,
        )
        for row in frame.itertuples(index=False):
            summaries.append(
                SyncRunRecord(
                    sync_run_id=str(row.sync_run_id),
                    workflow=str(row.workflow),
                    status=_as_run_status(row.status),
                    requested_at=_as_datetime(row.requested_at),
                    completed_at=_as_datetime(row.completed_at),
                    summary_path=str(row.summary_path),
                    artifact_dir=str(row.artifact_dir),
                    source_label=source_label,
                )
            )
    summaries.sort(key=lambda item: item.completed_at or item.requested_at or datetime.min, reverse=True)
    return summaries[:limit]


def load_sync_run_artifact_from_sources(sync_run_id: str, root: Path | None = None) -> SyncRunArtifact | None:
    for source_label, paths in get_browse_paths(root):
        if not paths.registry_path.exists():
            continue
        frame = _registry_frame(
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
            where sync_run_id = ?
            """.replace("?", f"'{sync_run_id}'"),
            paths=paths,
        )
        if frame.empty:
            continue

        row = frame.iloc[0]
        artifact_dir_value = str(row["artifact_dir"])
        artifact_dir_path = (
            _resolve_path(artifact_dir_value, paths.workspace_root)
            if artifact_dir_value
            else sync_run_dir(paths, sync_run_id)
        )
        if not artifact_dir_path.exists():
            continue

        manifest_path = artifact_dir_path / "manifest.json"
        manifest_payload = _read_json_file(manifest_path)
        manifest = SyncArtifactManifest.model_validate(manifest_payload) if isinstance(manifest_payload, dict) else None

        request_path = (
            _resolve_path(manifest.request_path, artifact_dir_path)
            if manifest is not None
            else artifact_dir_path / "request.json"
        )
        summary_path = (
            _resolve_path(manifest.summary_path, artifact_dir_path)
            if manifest is not None
            else _resolve_path(str(row["summary_path"]), artifact_dir_path)
        )
        validation_path = None
        if manifest is not None and manifest.validation_path is not None:
            validation_path = _resolve_path(manifest.validation_path, artifact_dir_path)
        else:
            candidate_validation = artifact_dir_path / "validation.json"
            if candidate_validation.exists():
                validation_path = candidate_validation

        request_payload = _read_artifact_payload(request_path) if request_path.exists() else None
        summary_payload = _read_artifact_payload(summary_path) if summary_path.exists() else None
        validation_payload = _read_artifact_payload(validation_path) if validation_path is not None and validation_path.exists() else None

        if manifest is None and request_payload is None and summary_payload is None and validation_payload is None:
            continue

        return SyncRunArtifact(
            sync_run_id=str(row["sync_run_id"]),
            workflow=str(manifest.workflow.value if manifest is not None else row["workflow"]),
            status=_as_run_status(manifest.status.value if manifest is not None else row["status"]),
            artifact_dir=str(artifact_dir_path),
            manifest=manifest,
            request_path=str(request_path) if request_path.exists() else None,
            summary_path=str(summary_path) if summary_path.exists() else None,
            validation_path=str(validation_path) if validation_path is not None and validation_path.exists() else None,
            request_payload=request_payload,
            summary_payload=summary_payload,
            validation_payload=validation_payload,
            source_label=source_label,
        )
    return None


def load_experiment_library_entries(root: Path | None = None) -> list[ExperimentLibraryEntry]:
    candidates = (
        app_root(root) / "experiments",
        app_root(root) / "library",
        get_app_paths(root).runs_root,
        get_app_paths(root).local_state_dir / "scans",
    )
    entries: list[ExperimentLibraryEntry] = []
    for base_dir in candidates:
        if not base_dir.exists():
            continue
        for path in sorted(base_dir.iterdir(), key=lambda item: item.name):
            stat = path.stat()
            item_count = len(list(path.iterdir())) if path.is_dir() else None
            label = path.relative_to(app_root(root)).as_posix()
            entries.append(
                ExperimentLibraryEntry(
                    label=label,
                    path=str(path),
                    kind="directory" if path.is_dir() else "file",
                    modified_at=datetime.fromtimestamp(stat.st_mtime),
                    item_count=item_count,
                )
            )
    entries.sort(key=lambda item: ((item.modified_at or datetime.min), item.label), reverse=True)
    return entries


def load_home_page_data(paths: AppPaths | None = None, limit: int = 10, root: Path | None = None) -> HomePageData:
    saved_readiness_summary = load_latest_saved_readiness_summary(paths=paths, root=root)
    if paths is not None:
        validation_summary = load_latest_validation_summary(paths=paths)
        validation_results: list[ValidationResultItem] = []
        if validation_summary is not None:
            for row in validation_summary.recent_results.itertuples(index=False):
                validation_results.append(
                    ValidationResultItem(
                        validation_run_id=str(row.validation_run_id),
                        dataset_name=str(row.dataset_name),
                        check_name=str(row.check_name),
                        severity=str(row.severity),
                        status=str(row.status),
                        details=str(row.details),
                    )
                )
        recent_runs = load_recent_runs(limit=limit, paths=paths)
        run_count = len(load_recent_runs(limit=100, paths=paths))
        provider_capabilities = load_provider_capabilities(paths=paths)
        file_manifest = load_file_manifest_summary(paths=paths)
        return HomePageData(
            recent_runs=recent_runs,
            validation_results=validation_results,
            validation_summary=validation_summary,
            readiness_summary=(
                saved_readiness_summary
                if saved_readiness_summary is not None
                else build_home_readiness_summary(
                    validation_summary=validation_summary,
                    provider_capabilities=provider_capabilities,
                    file_manifest=file_manifest,
                )
            ),
            default_template=default_template_summary(),
            latest_saved_template=load_latest_saved_template(paths=paths),
            data_health_note=latest_data_health_note(paths=paths),
            app_run_count=run_count,
            shared_run_count=run_count,
            scan_batches=[],
            experiment_library_entries=[],
            app_paths=paths,
            shared_paths=paths,
        )

    shared_paths = get_shared_paths(root)
    app_paths = get_app_paths(root)
    data_health = load_data_health_snapshot(root)
    recent_runs = load_recent_runs_catalog(limit=limit, root=root)
    return HomePageData(
        recent_runs=recent_runs,
        validation_results=data_health.validation_results,
        validation_summary=data_health.validation_summary,
        readiness_summary=(
            saved_readiness_summary
            if saved_readiness_summary is not None
            else build_home_readiness_summary(
                validation_summary=data_health.validation_summary,
                provider_capabilities=data_health.provider_capabilities,
                file_manifest=data_health.file_manifest,
            )
        ),
        default_template=default_template_summary(),
        latest_saved_template=load_latest_saved_template(root=root),
        data_health_note=data_health.note,
        app_run_count=len(load_recent_runs(limit=100, paths=app_paths, source_label="app")),
        shared_run_count=len(load_recent_runs(limit=100, paths=shared_paths, source_label="shared")),
        scan_batches=load_scan_batches(limit=10, root=root),
        experiment_library_entries=load_experiment_library_entries(root=root),
        app_paths=app_paths,
        shared_paths=shared_paths,
    )


def build_run_submission(config: BacktestRunConfig, run_requested: bool) -> RunSubmission:
    payload = config.model_dump(mode="json")
    summary = {
        "run_id": config.run_id,
        "strategy_name": config.strategy_name,
        "start_date": str(config.start_date),
        "end_date": str(config.end_date),
        "execution_mode": config.execution.mode.value,
        "run_requested": run_requested,
    }
    return RunSubmission(
        config=config,
        run_requested=run_requested,
        payload=payload,
        summary=summary,
    )


def latest_data_health_note(paths: AppPaths | None = None) -> str:
    summary = load_latest_validation_summary(paths=paths)
    if summary is None:
        return "No validation results are available yet."
    failed = summary.recent_results[
        ~summary.recent_results["status"].astype(str).str.lower().map(is_passing_validation_status)
    ]
    if failed.empty:
        return "Latest validation samples are clean."
    return f"{len(failed)} recent validation checks are not passing."


def build_home_readiness_summary(
    *,
    validation_summary: ValidationSummary | None,
    provider_capabilities: list[ProviderCapabilitySummary],
    file_manifest: list[FileManifestSummary],
) -> ReadinessSummary:
    if not provider_capabilities:
        return ReadinessSummary(
            status="warning",
            headline="No real provider data is available yet.",
            body=(
                "The workbench can still browse demo artifacts, but the provider registry does not have "
                "any capability rows yet."
            ),
            next_steps=[
                "Seed demo data for offline exploration.",
                "Add provider credentials or a local bundle, then run a sync/backfill.",
                "Return to Data Health after the first publish.",
            ],
        )

    supports_minute_bars = any(item.supports_minute_bars for item in provider_capabilities)
    supports_security_status_history = any(
        item.supports_security_status_history for item in provider_capabilities
    )

    if not supports_minute_bars:
        return ReadinessSummary(
            status="warning",
            headline="Provider access is not ready for minute-bar research.",
            body=(
                "The configured provider is registered, but it does not currently advertise minute bars."
            ),
            next_steps=[
                "Check the provider token, API key, or local bundle configuration.",
                "Publish minute bars before trying a live-data backtest.",
            ],
        )

    if not supports_security_status_history:
        return ReadinessSummary(
            status="warning",
            headline="Provider permissions are missing security-status history.",
            body=(
                "Minute bars are available, but status-history-driven preflight and replay checks still "
                "need that dataset."
            ),
            next_steps=[
                "Enable security-status history in the provider account or adapter.",
                "Run validation again after the next publish.",
            ],
        )

    if validation_summary is None or not file_manifest:
        return ReadinessSummary(
            status="info",
            headline="Provider looks ready, but no published datasets are visible yet.",
            body=(
                "Capability rows are present, but the local registry still has no published data to browse."
            ),
            next_steps=[
                "Run the sync or backfill flow to publish data.",
                "Use the seeded demo state if you want to explore the UI now.",
            ],
        )

    return ReadinessSummary(
        status="success",
        headline="Provider readiness looks good.",
        body=(
            "Minute bars and security-status history are available, and the local registry already has "
            "published datasets."
        ),
        next_steps=[
            "Open Single Backtest, Parameter Scan, or Replay Diagnostics as needed.",
            "Use Data Health to review validation samples.",
        ],
    )


def _read_scan_batch_result(path: Path) -> ScanBatchResult | None:
    payload = _read_json_file(path)
    if payload is None or not isinstance(payload, dict):
        return None
    return ScanBatchResult.model_validate(payload)


def _run_summaries_from_frame(frame: pd.DataFrame, paths: AppPaths, source_label: str) -> list[RunSummary]:
    metrics_map: dict[str, dict[str, Any]] = {}
    for row in frame.itertuples(index=False):
        if not row.metrics_path:
            continue
        metrics_payload = _read_json_file(_resolve_path(row.metrics_path, paths.workspace_root))
        if isinstance(metrics_payload, dict):
            metrics_map[str(row.run_id)] = metrics_payload

    summaries: list[RunSummary] = []
    for row in frame.itertuples(index=False):
        metrics_payload = metrics_map.get(str(row.run_id), {})
        summaries.append(
            RunSummary(
                run_id=str(row.run_id),
                strategy_name=str(row.strategy_name),
                start_date=str(row.start_date),
                end_date=str(row.end_date),
                execution_mode=str(row.execution_mode),
                status=_as_run_status(row.status),
                created_at=_as_datetime(row.created_at),
                completed_at=_as_datetime(row.completed_at),
                artifacts_dir=str(row.artifacts_dir),
                metrics_path=str(row.metrics_path) if row.metrics_path else None,
                total_return_pct=_safe_float(metrics_payload.get("total_return_pct")),
                max_drawdown_pct=_safe_float(metrics_payload.get("max_drawdown_pct")),
                trade_count=_safe_int(metrics_payload.get("trade_count")),
                source_label=source_label,
            )
        )
    return summaries


def _run_sort_key(summary: RunSummary) -> datetime:
    return summary.completed_at or summary.created_at or datetime.min


def _canonical_validation_status(value: Any) -> str:
    status = str(value).strip().lower()
    if status == "passed":
        return "pass"
    return status


def is_passing_validation_status(value: str) -> bool:
    return value in {"pass", "passed"}


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None


def _safe_int(value: Any) -> int | None:
    try:
        if value is None or pd.isna(value):
            return None
        return int(value)
    except Exception:
        return None


def _as_datetime(value: Any) -> datetime | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, datetime):
        return value
    if hasattr(value, "to_pydatetime"):
        return value.to_pydatetime()
    return None


def _as_run_status(value: Any) -> RunStatus | str:
    try:
        return RunStatus(str(value))
    except ValueError:
        return str(value)


def registry_bootstrap(paths: AppPaths | None = None) -> None:
    paths = paths or get_app_paths()
    bootstrap_registry(paths.registry_path)
