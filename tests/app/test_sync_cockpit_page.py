from __future__ import annotations

import runpy
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace


@dataclass(frozen=True)
class _ReadinessSummary:
    status: str
    headline: str
    body: str
    next_steps: list[str]


@dataclass(frozen=True)
class _Draft:
    submitted: bool
    payload: dict[str, object]
    summary: dict[str, object]


@dataclass(frozen=True)
class _Plan:
    workflow: str
    config_path: str | None
    dry_run: bool
    start_date: str
    end_date: str
    symbol_count: int
    windows: tuple[dict[str, object], ...] = ()
    reference_datasets: tuple[str, ...] = ()
    gap_scan: object | None = None


@dataclass(frozen=True)
class _SyncRunRecord:
    sync_run_id: str
    workflow: str
    status: str
    requested_at: datetime | None
    completed_at: datetime | None
    summary_path: str
    artifact_dir: str
    source_label: str = "app"


@dataclass(frozen=True)
class _SyncRunArtifact:
    sync_run_id: str
    workflow: str | None
    status: str | None
    artifact_dir: str
    manifest: object | None
    request_path: str | None
    summary_path: str | None
    validation_path: str | None
    request_payload: dict[str, object] | list[dict[str, object]] | str | None
    summary_payload: dict[str, object] | list[dict[str, object]] | str | None
    validation_payload: dict[str, object] | list[dict[str, object]] | str | None
    source_label: str = "app"


@dataclass(frozen=True)
class _SyncArtifactManifest:
    sync_run_id: str
    workflow: str
    status: str


class _FakeColumn:
    def __enter__(self) -> "_FakeColumn":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class _FakeExpander(_FakeColumn):
    pass


class _FakeSpinner(_FakeColumn):
    pass


class _FakeStreamlit(SimpleNamespace):
    def __init__(self, button_results: dict[str, bool] | None = None) -> None:
        super().__init__(session_state={}, query_params={})
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self._button_results = button_results or {}

    def set_page_config(self, **kwargs) -> None:
        self.calls.append(("set_page_config", tuple(sorted(kwargs.items()))))

    def title(self, *args) -> None:
        self.calls.append(("title", args))

    def caption(self, *args) -> None:
        self.calls.append(("caption", args))

    def subheader(self, *args) -> None:
        self.calls.append(("subheader", args))

    def success(self, *args) -> None:
        self.calls.append(("success", args))

    def warning(self, *args) -> None:
        self.calls.append(("warning", args))

    def info(self, *args) -> None:
        self.calls.append(("info", args))

    def error(self, *args) -> None:
        self.calls.append(("error", args))

    def write(self, *args) -> None:
        self.calls.append(("write", args))

    def markdown(self, *args, **kwargs) -> None:
        self.calls.append(("markdown", args))

    def json(self, *args, **kwargs) -> None:
        self.calls.append(("json", args))

    def code(self, *args, **kwargs) -> None:
        self.calls.append(("code", args))

    def dataframe(self, *args, **kwargs) -> None:
        self.calls.append(("dataframe", args))

    def columns(self, count: int | tuple[float, ...]) -> list[_FakeColumn]:
        self.calls.append(("columns", (count,)))
        column_count = len(count) if isinstance(count, tuple) else count
        return [_FakeColumn() for _ in range(column_count)]

    def divider(self) -> None:
        self.calls.append(("divider", ()))

    def button(self, *args, **kwargs):
        self.calls.append(("button", args))
        if kwargs.get("disabled"):
            return False
        label = str(args[0]) if args else ""
        return self._button_results.get(label, False)

    def selectbox(self, *args, **kwargs):
        self.calls.append(("selectbox", args))
        return kwargs.get("options", [None])[0]

    def expander(self, *args, **kwargs) -> _FakeExpander:
        self.calls.append(("expander", args))
        return _FakeExpander()

    def spinner(self, *args, **kwargs) -> _FakeSpinner:
        self.calls.append(("spinner", args))
        return _FakeSpinner()


def test_sync_cockpit_page_prepares_request_before_any_execution(tmp_path: Path, monkeypatch) -> None:
    import app.ui.data_access as data_access
    import app.ui.forms as forms
    import data.ingest.sync as sync

    fake_streamlit = _FakeStreamlit()
    readiness = _ReadinessSummary(
        status="success",
        headline="Saved readiness is available.",
        body="The cockpit should render this first.",
        next_steps=["No action needed."],
    )

    monkeypatch.setitem(sys.modules, "streamlit", fake_streamlit)
    monkeypatch.setattr(data_access, "load_latest_saved_readiness_summary", lambda *args, **kwargs: readiness)
    monkeypatch.setattr(data_access, "load_recent_sync_runs", lambda *args, **kwargs: [])
    monkeypatch.setattr(data_access, "load_sync_run_artifact_from_sources", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        forms,
        "render_sync_cockpit_form",
        lambda default_config=None: _Draft(
            submitted=True,
            payload={"workflow": "backfill", "start_date": "2026-03-01", "end_date": "2026-03-05"},
            summary={"workflow": "backfill", "window": "2026-03-01 to 2026-03-05"},
        ),
    )
    monkeypatch.setattr(
        sync,
        "build_backfill_plan",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("dry-run planning should not run")),
    )
    monkeypatch.setattr(
        sync,
        "build_refresh_plan",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("dry-run planning should not run")),
    )

    runpy.run_path(Path(__file__).resolve().parents[2] / "app/pages/6_同步驾驶舱.py", run_name="__main__")

    assert any(call[0] == "success" and "Saved readiness is available." in call[1][0] for call in fake_streamlit.calls)
    assert fake_streamlit.session_state["quantlab_pending_sync_request"]["workflow"] == "backfill"
    assert "quantlab_last_sync_execution" not in fake_streamlit.session_state
    assert next(call for call in fake_streamlit.calls if call[0] == "subheader")[1][0] == "最近一次数据源就绪检查"


def test_sync_cockpit_page_runs_dry_run_only_after_click(tmp_path: Path, monkeypatch) -> None:
    import app.ui.data_access as data_access
    import app.ui.forms as forms
    import data.ingest.sync as sync

    fake_streamlit = _FakeStreamlit(button_results={"执行 dry-run 规划": True})
    readiness = _ReadinessSummary(
        status="info",
        headline="Saved readiness is visible.",
        body="Dry-run planning is still explicit.",
        next_steps=["Click the run button."],
    )
    draft = _Draft(
        submitted=True,
        payload={
            "workflow": "backfill",
            "start_date": "2026-03-01",
            "end_date": "2026-03-05",
            "config_path": None,
            "symbols": ["000001", "600000"],
        },
        summary={"workflow": "backfill", "window": "2026-03-01 to 2026-03-05"},
    )
    called: list[tuple[str, object]] = []

    def fake_build_backfill_plan(*, paths, start_date, end_date, config_path=None, symbols=None, dry_run=True):
        called.append(("backfill", paths))
        return _Plan(
            workflow="backfill",
            config_path=None if config_path is None else str(config_path),
            dry_run=dry_run,
            start_date="2026-03-01",
            end_date="2026-03-05",
            symbol_count=2,
            windows=(
                {
                    "start_date": "2026-03-01",
                    "end_date": "2026-03-05",
                    "trade_dates": ["2026-03-02", "2026-03-03"],
                    "symbol_count": 2,
                    "expected_rows": 960,
                    "reason": "initial_backfill",
                },
            ),
            reference_datasets=("security_master", "trade_calendar"),
        )

    monkeypatch.setitem(sys.modules, "streamlit", fake_streamlit)
    monkeypatch.setattr(data_access, "load_latest_saved_readiness_summary", lambda *args, **kwargs: readiness)
    monkeypatch.setattr(data_access, "load_recent_sync_runs", lambda *args, **kwargs: [])
    monkeypatch.setattr(data_access, "load_sync_run_artifact_from_sources", lambda *args, **kwargs: None)
    monkeypatch.setattr(forms, "render_sync_cockpit_form", lambda default_config=None: draft)
    monkeypatch.setattr(sync, "build_backfill_plan", fake_build_backfill_plan)
    monkeypatch.setattr(
        sync,
        "build_refresh_plan",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("refresh planning should not run")),
    )

    runpy.run_path(Path(__file__).resolve().parents[2] / "app/pages/6_同步驾驶舱.py", run_name="__main__")

    assert called and called[0][0] == "backfill"
    assert fake_streamlit.session_state["quantlab_last_sync_execution"]["action"] == "dry-run"
    assert fake_streamlit.session_state["quantlab_last_sync_execution"]["payload"]["workflow"] == "backfill"
    assert any(call[0] == "success" and "Backfill dry-run" in call[1][0] for call in fake_streamlit.calls)


def test_sync_cockpit_page_runs_real_execution_only_when_hook_exists(tmp_path: Path, monkeypatch) -> None:
    import app.ui.data_access as data_access
    import app.ui.forms as forms
    import app.ui.workbench as workbench
    import data.ingest.sync as sync

    fake_streamlit = _FakeStreamlit(button_results={"执行真实同步": True})
    readiness = _ReadinessSummary(
        status="warning",
        headline="Saved readiness needs attention.",
        body="The cockpit can still plan dry-runs.",
        next_steps=["Fix the provider token."],
    )
    draft = _Draft(
        submitted=True,
        payload={
            "workflow": "daily-refresh",
            "end_date": "2026-03-05",
            "config_path": None,
            "symbols": [],
        },
        summary={"workflow": "daily-refresh", "window": "ending 2026-03-05"},
    )
    executed: list[dict[str, object]] = []

    monkeypatch.setitem(sys.modules, "streamlit", fake_streamlit)
    monkeypatch.setattr(data_access, "load_latest_saved_readiness_summary", lambda *args, **kwargs: readiness)
    monkeypatch.setattr(data_access, "load_recent_sync_runs", lambda *args, **kwargs: [])
    monkeypatch.setattr(data_access, "load_sync_run_artifact_from_sources", lambda *args, **kwargs: None)
    monkeypatch.setattr(forms, "render_sync_cockpit_form", lambda default_config=None: draft)
    monkeypatch.setattr(
        workbench,
        "detect_sync_runner",
        lambda: SimpleNamespace(available=True, message="Detected sync hook.", runner=lambda: None),
    )

    def fake_execute_sync_request(request, root=None):
        executed.append(request)
        return SimpleNamespace(
            success=True,
            message="Sync execution completed.",
            payload={"sync_run_id": "sync-001", "workflow": request["workflow"]},
            artifact_path=str(tmp_path / ".quantlab" / "sync_runs" / "sync-001"),
            sync_run_id="sync-001",
        )

    monkeypatch.setattr(workbench, "execute_sync_request", fake_execute_sync_request)
    monkeypatch.setattr(sync, "build_backfill_plan", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("backfill should not run")))
    monkeypatch.setattr(sync, "build_refresh_plan", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("refresh should not run")))

    runpy.run_path(Path(__file__).resolve().parents[2] / "app/pages/6_同步驾驶舱.py", run_name="__main__")

    assert executed and executed[0]["workflow"] == "daily-refresh"
    assert fake_streamlit.session_state["quantlab_last_sync_execution"]["action"] == "execute"
    assert fake_streamlit.session_state["quantlab_last_sync_execution"]["payload"]["sync_run_id"] == "sync-001"
    assert any(call[0] == "success" and "Sync execution completed." in call[1][0] for call in fake_streamlit.calls)


def test_sync_cockpit_page_browses_saved_sync_runs_without_a_runner_hook(
    tmp_path: Path, monkeypatch
) -> None:
    import app.ui.data_access as data_access
    import app.ui.forms as forms
    import app.ui.workbench as workbench

    fake_streamlit = _FakeStreamlit()
    readiness = _ReadinessSummary(
        status="success",
        headline="Saved readiness is available.",
        body="The page can still browse saved runs.",
        next_steps=["Open the latest sync run."],
    )
    draft = _Draft(
        submitted=True,
        payload={
            "workflow": "weekly-maintenance",
            "end_date": "2026-03-05",
            "config_path": None,
            "symbols": [],
        },
        summary={"workflow": "weekly-maintenance", "window": "ending 2026-03-05"},
    )
    runs = [
        _SyncRunRecord(
            sync_run_id="sync-002",
            workflow="weekly-maintenance",
            status="completed",
            requested_at=datetime(2026, 3, 28, 9, 0, 0),
            completed_at=datetime(2026, 3, 28, 9, 10, 0),
            summary_path=str(tmp_path / ".quantlab" / "sync_runs" / "sync-002" / "summary.json"),
            artifact_dir=str(tmp_path / ".quantlab" / "sync_runs" / "sync-002"),
            source_label="app",
        )
    ]
    artifact = _SyncRunArtifact(
        sync_run_id="sync-002",
        workflow="weekly-maintenance",
        status="completed",
        artifact_dir=runs[0].artifact_dir,
        manifest=_SyncArtifactManifest(sync_run_id="sync-002", workflow="weekly-maintenance", status="completed"),
        request_path=str(tmp_path / ".quantlab" / "sync_runs" / "sync-002" / "request.json"),
        summary_path=str(tmp_path / ".quantlab" / "sync_runs" / "sync-002" / "summary.json"),
        validation_path=None,
        request_payload={"workflow": "weekly-maintenance", "dry_run": False},
        summary_payload={"workflow": "weekly-maintenance", "minute_windows": []},
        validation_payload=None,
        source_label="app",
    )

    monkeypatch.setitem(sys.modules, "streamlit", fake_streamlit)
    monkeypatch.setattr(data_access, "load_latest_saved_readiness_summary", lambda *args, **kwargs: readiness)
    monkeypatch.setattr(data_access, "load_recent_sync_runs", lambda *args, **kwargs: runs)
    monkeypatch.setattr(data_access, "load_sync_run_artifact_from_sources", lambda *args, **kwargs: artifact)
    monkeypatch.setattr(forms, "render_sync_cockpit_form", lambda default_config=None: draft)
    monkeypatch.setattr(
        workbench,
        "detect_sync_runner",
        lambda: SimpleNamespace(
            available=False,
            message="No sync runner hook is available yet. You can still browse saved sync runs and plan dry-runs.",
            runner=None,
        ),
    )

    runpy.run_path(Path(__file__).resolve().parents[2] / "app/pages/6_同步驾驶舱.py", run_name="__main__")

    assert any(call[0] == "info" and "No sync runner hook is available yet" in call[1][0] for call in fake_streamlit.calls)
    assert any(call[0] == "dataframe" for call in fake_streamlit.calls)
    assert any(call[0] == "json" and isinstance(call[1][0], dict) for call in fake_streamlit.calls)
