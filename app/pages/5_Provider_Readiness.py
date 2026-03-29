from __future__ import annotations

import json
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.ui.data_access import load_latest_readiness_artifact  # noqa: E402
from app.ui.workbench import detect_provider_readiness_runner, execute_provider_readiness_check  # noqa: E402


st.set_page_config(page_title="Provider Readiness", layout="wide")


def _summary_to_dict(summary: object) -> dict[str, object]:
    return {
        "status": str(getattr(summary, "status", "info")),
        "headline": str(getattr(summary, "headline", "Provider readiness result")),
        "body": str(getattr(summary, "body", "")),
        "next_steps": list(getattr(summary, "next_steps", [])),
    }


def _render_summary(summary: object) -> None:
    status = str(getattr(summary, "status", "info")).lower()
    headline = str(getattr(summary, "headline", "Provider readiness result"))
    body = str(getattr(summary, "body", ""))
    next_steps = list(getattr(summary, "next_steps", []))

    if status == "success":
        st.success(f"{headline} {body}")
    elif status == "warning":
        st.warning(f"{headline} {body}")
    else:
        st.info(f"{headline} {body}")

    if next_steps:
        st.markdown("**Next steps**")
        for step in next_steps:
            st.markdown(f"- {step}")


st.title("Provider Readiness")
st.caption("Read the latest saved readiness artifact first. Checks only run when you click the button below.")

latest_artifact = load_latest_readiness_artifact()
probe = detect_provider_readiness_runner()

overview_col, action_col = st.columns((1.4, 1))
with overview_col:
    st.subheader("Latest saved result")
    if latest_artifact is None:
        st.info("No persisted readiness artifact is available yet.")
    else:
        st.caption(f"Loaded from `{latest_artifact.path}`")
        _render_summary(latest_artifact.summary)
        with st.expander("Raw saved artifact", expanded=False):
            payload = getattr(latest_artifact, "payload", None)
            if isinstance(payload, dict):
                st.code(json.dumps(payload, indent=2), language="json")
            elif isinstance(payload, list):
                st.code(json.dumps(payload, indent=2), language="json")
            elif payload is None:
                st.info("The saved artifact does not expose a raw payload.")
            else:
                st.code(str(payload))

with action_col:
    st.subheader("Execution")
    if probe.available:
        st.success(probe.message)
    else:
        st.info(probe.message)
    st.write("Nothing runs automatically. Click the button to execute the readiness checks.")
    run_now = st.button(
        "Run readiness checks now",
        type="primary",
        use_container_width=True,
        disabled=not probe.available,
    )
    if run_now:
        with st.spinner("Running readiness checks..."):
            result = execute_provider_readiness_check()
        st.session_state["quantlab_last_provider_readiness_check"] = {
            "success": bool(getattr(result, "success", False)),
            "message": str(getattr(result, "message", "")),
            "artifact_path": getattr(result, "artifact_path", None),
            "summary": None if getattr(result, "summary", None) is None else _summary_to_dict(getattr(result, "summary")),
        }

last_execution = st.session_state.get("quantlab_last_provider_readiness_check")
if last_execution is not None:
    st.divider()
    st.subheader("Last check")
    if last_execution["success"]:
        st.success(last_execution["message"])
    else:
        st.warning(last_execution["message"])
    st.json(last_execution)
