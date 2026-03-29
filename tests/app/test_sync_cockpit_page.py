from __future__ import annotations

import runpy
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from data.providers.tushare_provider import TushareConfigurationError


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
    def __init__(self, button_result: bool) -> None:
        super().__init__(session_state={}, query_params={})
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self._button_result = button_result

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

    def markdown(self, *args) -> None:
        self.calls.append(("markdown", args))

    def json(self, *args, **kwargs) -> None:
        self.calls.append(("json", args))

    def code(self, *args, **kwargs) -> None:
        self.calls.append(("code", args))

    def columns(self, count: int | tuple[float, ...]) -> list[_FakeColumn]:
        self.calls.append(("columns", (count,)))
        column_count = len(count) if isinstance(count, tuple) else count
        return [_FakeColumn() for _ in range(column_count)]

    def divider(self) -> None:
        self.calls.append(("divider", ()))

    def button(self, *args, **kwargs):
        self.calls.append(("button", args))
        return self._button_result

    def expander(self, *args, **kwargs) -> _FakeExpander:
        self.calls.append(("expander", args))
        return _FakeExpander()

    def spinner(self, *args, **kwargs) -> _FakeSpinner:
        self.calls.append(("spinner", args))
        return _FakeSpinner()


def test_sync_cockpit_page_shows_saved_readiness_and_waits_for_explicit_actions(
    tmp_path: Path, monkeypatch
) -> None:
    import app.ui.data_access as data_access
    import app.ui.forms as forms
    import data.ingest.sync as sync

    fake_streamlit = _FakeStreamlit(button_result=False)
    readiness = _ReadinessSummary(
        status="success",
        headline="Saved readiness is available.",
        body="The cockpit should render this first.",
        next_steps=["No action needed."],
    )

    monkeypatch.setitem(sys.modules, "streamlit", fake_streamlit)
    monkeypatch.setattr(data_access, "load_latest_saved_readiness_summary", lambda *args, **kwargs: readiness)
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

    runpy.run_path(Path(__file__).resolve().parents[2] / "app/pages/6_Sync_Cockpit.py", run_name="__main__")

    assert any(call[0] == "success" and "Saved readiness is available." in call[1][0] for call in fake_streamlit.calls)
    assert fake_streamlit.session_state["quantlab_pending_sync_request"]["workflow"] == "backfill"
    assert "quantlab_last_sync_execution" not in fake_streamlit.session_state


def test_sync_cockpit_page_runs_backfill_dry_run_only_after_explicit_click(
    tmp_path: Path, monkeypatch
) -> None:
    import app.ui.data_access as data_access
    import app.ui.forms as forms
    import data.ingest.sync as sync

    fake_streamlit = _FakeStreamlit(button_result=True)
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
    monkeypatch.setattr(forms, "render_sync_cockpit_form", lambda default_config=None: draft)
    monkeypatch.setattr(sync, "build_backfill_plan", fake_build_backfill_plan)
    monkeypatch.setattr(
        sync,
        "build_refresh_plan",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("refresh planning should not run")),
    )

    runpy.run_path(Path(__file__).resolve().parents[2] / "app/pages/6_Sync_Cockpit.py", run_name="__main__")

    assert called and called[0][0] == "backfill"
    assert fake_streamlit.session_state["quantlab_last_sync_execution"]["success"] is True
    assert fake_streamlit.session_state["quantlab_last_sync_execution"]["plan"]["workflow"] == "backfill"
    assert any(call[0] == "success" and "Backfill dry-run" in call[1][0] for call in fake_streamlit.calls)


def test_sync_cockpit_page_renders_the_latest_dry_run_error_clearly(tmp_path: Path, monkeypatch) -> None:
    import app.ui.data_access as data_access
    import app.ui.forms as forms
    import data.ingest.sync as sync

    fake_streamlit = _FakeStreamlit(button_result=True)
    readiness = _ReadinessSummary(
        status="warning",
        headline="Saved readiness needs attention.",
        body="The cockpit can still plan dry-runs.",
        next_steps=["Fix the provider token."],
    )
    draft = _Draft(
        submitted=True,
        payload={
            "workflow": "weekly-maintenance",
            "end_date": "2026-03-05",
            "config_path": None,
            "symbols": [],
        },
        summary={"workflow": "weekly-maintenance", "window": "maintenance ending 2026-03-05"},
    )

    def fake_build_refresh_plan(*, paths, end_date=None, workflow="daily-refresh", config_path=None, symbols=None, dry_run=True):
        raise RuntimeError("no trade dates available for refresh planning")

    monkeypatch.setitem(sys.modules, "streamlit", fake_streamlit)
    monkeypatch.setattr(data_access, "load_latest_saved_readiness_summary", lambda *args, **kwargs: readiness)
    monkeypatch.setattr(forms, "render_sync_cockpit_form", lambda default_config=None: draft)
    monkeypatch.setattr(sync, "build_backfill_plan", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("backfill should not run")))
    monkeypatch.setattr(sync, "build_refresh_plan", fake_build_refresh_plan)

    runpy.run_path(Path(__file__).resolve().parents[2] / "app/pages/6_Sync_Cockpit.py", run_name="__main__")

    last_execution = fake_streamlit.session_state["quantlab_last_sync_execution"]
    assert last_execution["success"] is False
    assert "no trade dates available" in last_execution["message"]
    assert any(call[0] == "error" and "no trade dates available" in call[1][0] for call in fake_streamlit.calls)


def test_sync_cockpit_page_formats_actionable_blocker_messages(tmp_path: Path, monkeypatch) -> None:
    import app.ui.data_access as data_access
    import app.ui.forms as forms
    import data.ingest.sync as sync

    fake_streamlit = _FakeStreamlit(button_result=True)
    readiness = _ReadinessSummary(
        status="warning",
        headline="Saved readiness needs attention.",
        body="The cockpit should still explain blockers clearly.",
        next_steps=["Fix provider permissions."],
    )
    draft = _Draft(
        submitted=True,
        payload={
            "workflow": "backfill",
            "start_date": "2026-03-01",
            "end_date": "2026-03-05",
            "config_path": None,
            "symbols": [],
        },
        summary={"workflow": "backfill", "window": "2026-03-01 to 2026-03-05"},
    )

    def fake_build_backfill_plan(*, paths, start_date, end_date, config_path=None, symbols=None, dry_run=True):
        raise TushareConfigurationError(
            "Tushare permission error for stk_mins: 权限不足. Minute-data permission is missing for this token."
        )

    monkeypatch.setitem(sys.modules, "streamlit", fake_streamlit)
    monkeypatch.setattr(data_access, "load_latest_saved_readiness_summary", lambda *args, **kwargs: readiness)
    monkeypatch.setattr(forms, "render_sync_cockpit_form", lambda default_config=None: draft)
    monkeypatch.setattr(sync, "build_backfill_plan", fake_build_backfill_plan)
    monkeypatch.setattr(sync, "build_refresh_plan", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("refresh should not run")))

    runpy.run_path(Path(__file__).resolve().parents[2] / "app/pages/6_Sync_Cockpit.py", run_name="__main__")

    last_execution = fake_streamlit.session_state["quantlab_last_sync_execution"]
    assert last_execution["success"] is False
    assert "minute-data permission is missing" in last_execution["message"].lower()
    assert any(call[0] == "error" and "minute-data permission is missing" in call[1][0].lower() for call in fake_streamlit.calls)
