from __future__ import annotations

import runpy
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace


@dataclass(frozen=True)
class _ReadinessSummary:
    status: str
    headline: str
    body: str
    next_steps: list[str]


@dataclass(frozen=True)
class _Artifact:
    path: str
    summary: _ReadinessSummary


class _FakeColumn:
    def __enter__(self) -> "_FakeColumn":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class _FakeSpinner(_FakeColumn):
    pass


class _FakeExpander(_FakeColumn):
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

    def write(self, *args) -> None:
        self.calls.append(("write", args))

    def markdown(self, *args) -> None:
        self.calls.append(("markdown", args))

    def code(self, *args, **kwargs) -> None:
        self.calls.append(("code", args))

    def json(self, *args, **kwargs) -> None:
        self.calls.append(("json", args))

    def columns(self, count: int | tuple[float, ...]) -> list[_FakeColumn]:
        self.calls.append(("columns", (count,)))
        column_count = len(count) if isinstance(count, tuple) else count
        return [_FakeColumn() for _ in range(column_count)]

    def divider(self) -> None:
        self.calls.append(("divider", ()))

    def button(self, *args, **kwargs):
        self.calls.append(("button", args))
        return self._button_result

    def spinner(self, *args, **kwargs) -> _FakeSpinner:
        self.calls.append(("spinner", args))
        return _FakeSpinner()

    def expander(self, *args, **kwargs) -> _FakeExpander:
        self.calls.append(("expander", args))
        return _FakeExpander()


def test_provider_readiness_page_shows_saved_artifact_without_running_checks(tmp_path: Path, monkeypatch) -> None:
    import app.ui.data_access as data_access
    import app.ui.workbench as workbench

    fake_streamlit = _FakeStreamlit(button_result=False)
    saved_artifact = _Artifact(
        path=str(tmp_path / ".quantlab" / "readiness" / "latest.json"),
        summary=_ReadinessSummary(
            status="success",
            headline="Saved readiness is available.",
            body="This should render before any check runs.",
            next_steps=["No-op."],
        ),
    )

    monkeypatch.setitem(sys.modules, "streamlit", fake_streamlit)
    monkeypatch.setattr(data_access, "load_latest_readiness_artifact", lambda *args, **kwargs: saved_artifact)
    monkeypatch.setattr(
        workbench,
        "detect_provider_readiness_runner",
        lambda: SimpleNamespace(available=True, message="Detected readiness hook.", runner=lambda: None),
    )
    monkeypatch.setattr(
        workbench,
        "execute_provider_readiness_check",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("readiness check should not run")),
    )

    runpy.run_path(Path(__file__).resolve().parents[2] / "app/pages/5_Provider_Readiness.py", run_name="__main__")

    assert any(call[0] == "success" and "Saved readiness is available." in call[1][0] for call in fake_streamlit.calls)
    assert "quantlab_last_provider_readiness_check" not in fake_streamlit.session_state


def test_provider_readiness_page_runs_only_after_button_click(tmp_path: Path, monkeypatch) -> None:
    import app.ui.data_access as data_access
    import app.ui.workbench as workbench

    fake_streamlit = _FakeStreamlit(button_result=True)
    saved_artifact = _Artifact(
        path=str(tmp_path / ".quantlab" / "readiness" / "latest.json"),
        summary=_ReadinessSummary(
            status="info",
            headline="Saved readiness is visible.",
            body="A fresh check may be requested explicitly.",
            next_steps=["Click the button."],
        ),
    )

    executed = {"count": 0}

    def fake_execute_provider_readiness_check(*args, **kwargs):
        executed["count"] += 1
        return SimpleNamespace(
            success=True,
            message="Readiness check completed.",
            summary=SimpleNamespace(
                status="success",
                headline="Fresh readiness check passed.",
                body="The new run finished successfully.",
                next_steps=["Review the artifacts."],
            ),
            artifact_path=saved_artifact.path,
        )

    monkeypatch.setitem(sys.modules, "streamlit", fake_streamlit)
    monkeypatch.setattr(data_access, "load_latest_readiness_artifact", lambda *args, **kwargs: saved_artifact)
    monkeypatch.setattr(
        workbench,
        "detect_provider_readiness_runner",
        lambda: SimpleNamespace(available=True, message="Detected readiness hook.", runner=lambda: None),
    )
    monkeypatch.setattr(workbench, "execute_provider_readiness_check", fake_execute_provider_readiness_check)

    runpy.run_path(Path(__file__).resolve().parents[2] / "app/pages/5_Provider_Readiness.py", run_name="__main__")

    assert executed["count"] == 1
    assert fake_streamlit.session_state["quantlab_last_provider_readiness_check"]["message"] == "Readiness check completed."
    assert any(call[0] == "success" and "Readiness check completed." in call[1][0] for call in fake_streamlit.calls)
