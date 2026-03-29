from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import duckdb

from quantlab.config import AppPaths
from quantlab.registry import bootstrap_registry
from quantlab.storage import ensure_state_dirs, sync_run_dir


def _paths(tmp_path: Path) -> AppPaths:
    paths = AppPaths.from_workspace(tmp_path)
    ensure_state_dirs(paths)
    bootstrap_registry(paths.registry_path)
    return paths


def test_recent_sync_runs_loader_reads_registry_rows(tmp_path: Path) -> None:
    from app.ui.data_access import load_recent_sync_runs

    paths = _paths(tmp_path)
    with duckdb.connect(str(paths.registry_path)) as connection:
        connection.execute(
            """
            insert into sync_runs (
                sync_run_id, workflow, status, requested_at, completed_at, summary_path, artifact_dir
            ) values
                ('sync-001', 'daily-refresh', 'completed', ?, ?, '/tmp/sync-001/summary.json', '/tmp/sync-001'),
                ('sync-002', 'weekly-maintenance', 'created', ?, null, '/tmp/sync-002/summary.json', '/tmp/sync-002')
            """,
            [
                datetime(2026, 3, 28, 9, 0, 0),
                datetime(2026, 3, 28, 11, 10, 0),
                datetime(2026, 3, 28, 10, 0, 0),
            ],
        )

    runs = load_recent_sync_runs(limit=5, root=tmp_path)

    assert [run.sync_run_id for run in runs] == ["sync-001", "sync-002"]
    assert runs[0].workflow == "daily-refresh"
    assert runs[0].source_label == "shared"
    assert runs[0].completed_at == datetime(2026, 3, 28, 11, 10, 0)


def test_sync_run_artifact_loader_reads_manifest_and_payloads(tmp_path: Path) -> None:
    from app.ui.data_access import load_sync_run_artifact_from_sources

    paths = _paths(tmp_path)
    artifact_dir = sync_run_dir(paths, "sync-003")
    artifact_dir.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(paths.registry_path)) as connection:
        connection.execute(
            """
            insert into sync_runs (
                sync_run_id, workflow, status, requested_at, completed_at, summary_path, artifact_dir
            ) values
                ('sync-003', 'weekly-maintenance', 'completed', ?, ?, ?, ?)
            """,
            [
                datetime(2026, 3, 28, 11, 0, 0),
                datetime(2026, 3, 28, 11, 20, 0),
                str(artifact_dir / "summary.json"),
                str(artifact_dir),
            ],
        )

    (artifact_dir / "manifest.json").write_text(
        json.dumps(
            {
                "sync_run_id": "sync-003",
                "workflow": "weekly-maintenance",
                "status": "completed",
                "request_path": "request.json",
                "summary_path": "summary.json",
                "validation_path": "validation.json",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (artifact_dir / "request.json").write_text(
        json.dumps({"workflow": "weekly-maintenance", "dry_run": False}, indent=2),
        encoding="utf-8",
    )
    (artifact_dir / "summary.json").write_text(
        json.dumps({"workflow": "weekly-maintenance", "minute_windows": []}, indent=2),
        encoding="utf-8",
    )
    (artifact_dir / "validation.json").write_text(
        json.dumps({"status": "ok", "details": "saved validation"}, indent=2),
        encoding="utf-8",
    )

    artifact = load_sync_run_artifact_from_sources("sync-003", root=tmp_path)

    assert artifact is not None
    assert artifact.sync_run_id == "sync-003"
    assert artifact.workflow == "weekly-maintenance"
    assert artifact.manifest is not None
    assert artifact.manifest.workflow.value == "weekly-maintenance"
    assert isinstance(artifact.request_payload, dict)
    assert artifact.request_payload["dry_run"] is False
    assert isinstance(artifact.summary_payload, dict)
    assert artifact.summary_payload["workflow"] == "weekly-maintenance"
    assert isinstance(artifact.validation_payload, dict)
    assert artifact.validation_payload["status"] == "ok"
