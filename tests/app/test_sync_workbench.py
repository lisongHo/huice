from __future__ import annotations

from pathlib import Path
from types import ModuleType


def test_detect_sync_runner_and_execute_sync_request_calls_the_hook(tmp_path: Path, monkeypatch) -> None:
    import sys

    import app.ui.workbench as workbench

    captured: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def run_sync(*args, **kwargs):
        captured.append((args, kwargs))
        return {
            "success": True,
            "message": "Sync hook completed.",
            "sync_run_id": "sync-123",
            "artifact_path": str(tmp_path / ".quantlab" / "sync_runs" / "sync-123"),
            "payload": {"workflow": "daily-refresh"},
        }

    fake_module = ModuleType("fake_sync_hook")
    fake_module.run_sync = run_sync  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "fake_sync_hook", fake_module)
    monkeypatch.setattr(workbench, "SYNC_RUNNER_CANDIDATES", (("fake_sync_hook", "run_sync"),))

    probe = workbench.detect_sync_runner()
    result = workbench.execute_sync_request({"workflow": "daily-refresh", "end_date": "2026-03-05"}, root=tmp_path)

    assert probe.available is True
    assert probe.runner_name == "fake_sync_hook.run_sync"
    assert result.success is True
    assert result.message == "Sync hook completed."
    assert result.sync_run_id == "sync-123"
    assert result.payload["payload"]["workflow"] == "daily-refresh"
    assert captured and captured[0][0][1]["dry_run"] is False


def test_execute_sync_request_reports_missing_hook_clearly(tmp_path: Path, monkeypatch) -> None:
    import app.ui.workbench as workbench

    monkeypatch.setattr(workbench, "SYNC_RUNNER_CANDIDATES", ())

    result = workbench.execute_sync_request({"workflow": "daily-refresh"}, root=tmp_path)

    assert result.success is False
    assert "No sync runner hook is available yet" in result.message
    assert result.paths.workspace_root == tmp_path.resolve()
