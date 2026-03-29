from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import duckdb

from quantlab.config import AppPaths
from quantlab.registry import bootstrap_registry
from quantlab.schemas import RunStatus, SyncRunRequest, SyncWorkflow
from quantlab.storage import ensure_state_dirs, sync_run_dir
from reports import load_recent_sync_runs, load_sync_run_payload, persist_sync_run_result


def _paths(tmp_path: Path) -> AppPaths:
    paths = AppPaths.from_workspace(tmp_path)
    ensure_state_dirs(paths)
    bootstrap_registry(paths.registry_path)
    return paths


def test_persist_sync_run_result_round_trips_payload_and_registry_row(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    request = SyncRunRequest(
        sync_run_id="sync-run-001",
        workflow=SyncWorkflow.BACKFILL,
        start_date="2026-03-01",
        end_date="2026-03-02",
        config_path="/tmp/sync.toml",
        symbols=["000001", "600000"],
        dry_run=True,
    )
    summary = {
        "status": "completed",
        "rows_synced": 12,
        "notes": ["loaded minute bars", "wrote daily snapshot"],
    }
    validation = {"checks": [{"name": "row-count", "status": "ok"}]}
    requested_at = datetime(2026, 3, 29, 1, 2, 3, 123456)
    completed_at = datetime(2026, 3, 29, 1, 2, 4, 234567)

    manifest = persist_sync_run_result(
        paths,
        request,
        summary,
        validation=validation,
        requested_at=requested_at,
        completed_at=completed_at,
    )
    artifact_dir = sync_run_dir(paths, request.sync_run_id)
    payload = load_sync_run_payload(paths, request.sync_run_id)

    assert artifact_dir.exists()
    assert sorted(path.name for path in artifact_dir.iterdir()) == [
        "manifest.json",
        "request.json",
        "summary.json",
        "validation.json",
    ]
    assert json.loads((artifact_dir / "request.json").read_text()) == request.model_dump(mode="json")
    assert json.loads((artifact_dir / "summary.json").read_text()) == summary
    assert json.loads((artifact_dir / "validation.json").read_text()) == validation
    assert json.loads((artifact_dir / "manifest.json").read_text()) == manifest.model_dump(mode="json")
    assert payload is not None
    assert payload.manifest == manifest
    assert payload.request == request
    assert payload.summary == summary
    assert payload.validation == validation

    with duckdb.connect(str(paths.registry_path)) as connection:
        row = connection.execute(
            """
            select sync_run_id, workflow, status, requested_at, completed_at, summary_path, artifact_dir
            from sync_runs
            where sync_run_id = ?
            """,
            [request.sync_run_id],
        ).fetchone()

    assert row == (
        request.sync_run_id,
        request.workflow.value,
        RunStatus.COMPLETED.value,
        requested_at,
        completed_at,
        str(artifact_dir / "summary.json"),
        str(artifact_dir),
    )


def test_load_recent_sync_runs_orders_newest_first_and_handles_missing_validation(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    older_request = SyncRunRequest(
        sync_run_id="sync-run-older",
        workflow=SyncWorkflow.DAILY_REFRESH,
        symbols=["000001"],
    )
    newer_request = SyncRunRequest(
        sync_run_id="sync-run-newer",
        workflow=SyncWorkflow.WEEKLY_MAINTENANCE,
        symbols=["600000"],
    )

    persist_sync_run_result(
        paths,
        older_request,
        {"status": "completed", "rows_synced": 1},
        requested_at=datetime(2026, 3, 29, 1, 2, 3, 0),
        completed_at=datetime(2026, 3, 29, 1, 2, 4, 0),
    )
    persist_sync_run_result(
        paths,
        newer_request,
        {"status": "completed", "rows_synced": 2},
        requested_at=datetime(2026, 3, 29, 2, 2, 3, 0),
        completed_at=datetime(2026, 3, 29, 2, 2, 4, 0),
    )

    recent = load_recent_sync_runs(paths, limit=5)
    payload = load_sync_run_payload(paths, older_request.sync_run_id)

    assert [run.sync_run_id for run in recent] == [newer_request.sync_run_id, older_request.sync_run_id]
    assert recent[0].workflow == SyncWorkflow.WEEKLY_MAINTENANCE
    assert recent[1].workflow == SyncWorkflow.DAILY_REFRESH
    assert payload is not None
    assert payload.validation is None
    assert not (sync_run_dir(paths, older_request.sync_run_id) / "validation.json").exists()
