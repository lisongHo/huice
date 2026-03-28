from __future__ import annotations

import builtins
import runpy
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from quantlab.config import AppPaths


@dataclass(frozen=True)
class _Draft:
    submitted: bool
    payload: dict[str, object]
    summary: dict[str, object]
    config: object | None = None


class _FakeColumn:
    def __enter__(self) -> "_FakeColumn":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class _FakeExpander(_FakeColumn):
    pass


class _FakeStreamlit(SimpleNamespace):
    def __init__(self) -> None:
        super().__init__(session_state={}, query_params={})
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def set_page_config(self, **kwargs) -> None:
        self.calls.append(("set_page_config", tuple(sorted(kwargs.items()))))

    def title(self, *args) -> None:
        self.calls.append(("title", args))

    def caption(self, *args) -> None:
        self.calls.append(("caption", args))

    def subheader(self, *args) -> None:
        self.calls.append(("subheader", args))

    def divider(self) -> None:
        self.calls.append(("divider", ()))

    def columns(self, count: int | tuple[float, ...]) -> list[_FakeColumn]:
        self.calls.append(("columns", (count,)))
        column_count = len(count) if isinstance(count, tuple) else count
        return [_FakeColumn() for _ in range(column_count)]

    def info(self, *args) -> None:
        self.calls.append(("info", args))

    def success(self, *args) -> None:
        self.calls.append(("success", args))

    def error(self, *args) -> None:
        self.calls.append(("error", args))

    def warning(self, *args) -> None:
        self.calls.append(("warning", args))

    def write(self, *args) -> None:
        self.calls.append(("write", args))

    def json(self, *args, **kwargs) -> None:
        self.calls.append(("json", args))

    def code(self, *args, **kwargs) -> None:
        self.calls.append(("code", args))

    def dataframe(self, *args, **kwargs) -> None:
        self.calls.append(("dataframe", args))

    def plotly_chart(self, *args, **kwargs) -> None:
        self.calls.append(("plotly_chart", args))

    def metric(self, *args, **kwargs) -> None:
        self.calls.append(("metric", args))

    def checkbox(self, *args, **kwargs):
        self.calls.append(("checkbox", args))
        return kwargs.get("value", False)

    def button(self, *args, **kwargs):
        self.calls.append(("button", args))
        return False

    def selectbox(self, *args, **kwargs):
        self.calls.append(("selectbox", args))
        return kwargs.get("options", [None])[0]

    def expander(self, *args, **kwargs) -> _FakeExpander:
        self.calls.append(("expander", args))
        return _FakeExpander()


def test_single_backtest_page_only_prepares_a_request_snapshot(tmp_path: Path, monkeypatch) -> None:
    import app.ui.data_access as data_access
    import app.ui.forms as forms

    fake_streamlit = _FakeStreamlit()
    paths = AppPaths.from_workspace(tmp_path)
    draft = _Draft(
        submitted=True,
        payload={"run_id": "draft-001", "strategy_name": "builtin_consecutive_down_rsi"},
        summary={"run_requested": True, "strategy_name": "builtin_consecutive_down_rsi"},
    )

    monkeypatch.setitem(sys.modules, "streamlit", fake_streamlit)
    monkeypatch.setattr(data_access, "get_app_paths", lambda: paths)
    monkeypatch.setattr(data_access, "default_template_summary", lambda: SimpleNamespace(config=None))
    monkeypatch.setattr(data_access, "load_latest_saved_template", lambda paths=None: None)
    monkeypatch.setattr(data_access, "load_latest_validation_summary", lambda paths=None: None)
    monkeypatch.setattr(data_access, "latest_data_health_note", lambda paths=None: "No validation results are available yet.")
    monkeypatch.setattr(data_access, "load_recent_runs", lambda limit=25, paths=None: [])
    monkeypatch.setattr(data_access, "load_recent_runs_catalog", lambda limit=30, root=None: [])
    monkeypatch.setattr(forms, "render_single_backtest_form", lambda default_config=None: draft)

    original_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name.startswith("backtest.core.engine") or name.startswith("reports.artifacts"):
            raise AssertionError(f"page should not import {name}")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    runpy.run_path(Path(__file__).resolve().parents[2] / "app/pages/1_Single_Backtest.py", run_name="__main__")

    assert fake_streamlit.session_state["quantlab_pending_backtest_request"] == draft.payload
    assert not (paths.runs_root.exists() and any(paths.runs_root.iterdir()))
