from __future__ import annotations

import runpy
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from quantlab.config import AppPaths


@dataclass(frozen=True)
class _Readiness:
    status: str
    headline: str
    body: str
    next_steps: list[str]


@dataclass(frozen=True)
class _Template:
    strategy_name: str = "builtin_consecutive_down_rsi"
    execution_mode: str = "last_5m_vwap"
    notes: str = "Default built-in template."
    start_date: str | None = None
    end_date: str | None = None


class _FakeColumn:
    def __enter__(self) -> "_FakeColumn":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


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

    def success(self, *args) -> None:
        self.calls.append(("success", args))

    def warning(self, *args) -> None:
        self.calls.append(("warning", args))

    def info(self, *args) -> None:
        self.calls.append(("info", args))

    def markdown(self, *args) -> None:
        self.calls.append(("markdown", args))

    def metric(self, *args, **kwargs) -> None:
        self.calls.append(("metric", args))

    def columns(self, count: int | tuple[float, ...]) -> list[_FakeColumn]:
        self.calls.append(("columns", (count,)))
        column_count = len(count) if isinstance(count, tuple) else count
        return [_FakeColumn() for _ in range(column_count)]

    def subheader(self, *args) -> None:
        self.calls.append(("subheader", args))

    def write(self, *args) -> None:
        self.calls.append(("write", args))

    def dataframe(self, *args, **kwargs) -> None:
        self.calls.append(("dataframe", args))

    def divider(self) -> None:
        self.calls.append(("divider", ()))

    def code(self, *args, **kwargs) -> None:
        self.calls.append(("code", args))


def test_home_page_shows_preflight_banner_and_next_steps(tmp_path: Path, monkeypatch) -> None:
    import app.ui.data_access as data_access

    fake_streamlit = _FakeStreamlit()
    readiness = _Readiness(
        status="warning",
        headline="No real provider data is available yet.",
        body="The workbench can still browse demo artifacts.",
        next_steps=["Seed demo data.", "Add provider credentials."],
    )
    fake_home = SimpleNamespace(
        recent_runs=[],
        validation_results=[],
        validation_summary=None,
        readiness_summary=readiness,
        default_template=_Template(),
        latest_saved_template=None,
        data_health_note="No validation results are available yet.",
        app_run_count=0,
        shared_run_count=0,
        scan_batches=[],
        experiment_library_entries=[],
        app_paths=AppPaths.from_workspace(tmp_path),
        shared_paths=AppPaths.from_workspace(tmp_path),
    )

    monkeypatch.setitem(sys.modules, "streamlit", fake_streamlit)
    monkeypatch.setattr(data_access, "load_home_page_data", lambda limit=12: fake_home)

    runpy.run_path(Path(__file__).resolve().parents[2] / "app/Home.py", run_name="__main__")

    assert any(call[0] == "warning" for call in fake_streamlit.calls)
    assert any(call[0] == "markdown" and call[1][0] == "**Next steps**" for call in fake_streamlit.calls)
    assert any(call[0] == "markdown" and call[1][0] == "- Seed demo data." for call in fake_streamlit.calls)
