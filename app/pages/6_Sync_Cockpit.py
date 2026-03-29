from __future__ import annotations

import json
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.ui.data_access import (  # noqa: E402
    load_latest_saved_readiness_summary,
    load_recent_sync_runs,
    load_sync_run_artifact_from_sources,
)
from app.ui.forms import render_sync_cockpit_form  # noqa: E402
from app.ui.workbench import (  # noqa: E402
    build_shared_paths,
    detect_sync_runner,
    execute_sync_request,
)
from data.ingest.sync import (  # noqa: E402
    build_backfill_plan,
    build_refresh_plan,
    sync_plan_to_dict,
)
from data.providers.tushare_readiness import (  # noqa: E402
    classify_tushare_planning_blocker,
    format_tushare_planning_blocker,
)


st.set_page_config(page_title="Sync Cockpit", layout="wide")


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


def _to_jsonish(payload: object) -> object:
    if payload is None:
        return None
    if hasattr(payload, "model_dump"):
        return payload.model_dump(mode="json")  # type: ignore[call-arg]
    if is_dataclass(payload):
        return asdict(payload)
    return payload


def _render_payload(payload: object) -> None:
    if payload is None:
        st.info("No saved payload is available for this run.")
        return

    jsonish = _to_jsonish(payload)
    if isinstance(jsonish, (dict, list)):
        st.json(jsonish)
    else:
        st.code(str(jsonish))


def _workflow_label(workflow: str) -> str:
    return workflow.replace("-", " ").replace("_", " ").title()


def _build_plan(request: dict[str, object], paths) -> dict[str, object]:
    workflow = str(request.get("workflow", "backfill"))
    config_path_value = request.get("config_path")
    config_path = Path(str(config_path_value)) if config_path_value else None
    symbols = request.get("symbols")
    symbols_list = list(symbols) if isinstance(symbols, list) else None

    try:
        if workflow == "backfill":
            plan = build_backfill_plan(
                paths=paths,
                start_date=str(request["start_date"]),
                end_date=str(request["end_date"]),
                config_path=config_path,
                symbols=symbols_list,
                dry_run=True,
            )
            return {
                "success": True,
                "workflow": workflow,
                "message": "Backfill dry-run plan is ready.",
                "payload": _to_jsonish(sync_plan_to_dict(plan)),
            }

        plan = build_refresh_plan(
            paths=paths,
            end_date=str(request.get("end_date")) if request.get("end_date") else None,
            workflow=workflow,
            config_path=config_path,
            symbols=symbols_list,
            dry_run=True,
        )
        return {
            "success": True,
            "workflow": workflow,
            "message": f"{_workflow_label(workflow)} dry-run plan is ready.",
            "payload": _to_jsonish(sync_plan_to_dict(plan)),
        }
    except Exception as exc:
        blocker = classify_tushare_planning_blocker(exc)
        if blocker is not None:
            return {
                "success": False,
                "workflow": workflow,
                "message": format_tushare_planning_blocker(
                    blocker,
                    workflow=_workflow_label(workflow),
                    dry_run=True,
                ),
                "error": str(exc),
                "next_steps": list(blocker.next_steps),
                "error_type": blocker.error_type,
            }
        return {
            "success": False,
            "workflow": workflow,
            "message": f"{_workflow_label(workflow)} dry-run planning failed: {exc}",
            "error": str(exc),
        }


st.title("Sync Cockpit")
st.caption(
    "Prepare a sync request explicitly, then choose dry-run planning or real execution from the buttons. "
    "Saved readiness and saved runs stay browseable even when the runner hook is missing."
)

latest_readiness = load_latest_saved_readiness_summary()
sync_paths = build_shared_paths(ROOT)
probe = detect_sync_runner()

overview_col, request_col = st.columns((1.25, 1))
with overview_col:
    st.subheader("Latest saved provider readiness")
    if latest_readiness is None:
        st.info("No persisted readiness summary is available yet.")
    else:
        _render_summary(latest_readiness)
        with st.expander("Raw saved readiness summary", expanded=False):
            st.code(
                json.dumps(
                    {
                        "status": str(getattr(latest_readiness, "status", "info")),
                        "headline": str(getattr(latest_readiness, "headline", "")),
                        "body": str(getattr(latest_readiness, "body", "")),
                        "next_steps": list(getattr(latest_readiness, "next_steps", [])),
                    },
                    indent=2,
                ),
                language="json",
            )

with request_col:
    st.subheader("Prepare sync request")
    draft = render_sync_cockpit_form()
    if draft.submitted:
        st.session_state["quantlab_pending_sync_request"] = draft.payload
        st.session_state["quantlab_pending_sync_summary"] = draft.summary
        st.success("Sync request prepared. Nothing runs until you click a planning or execution button.")

    pending_request = st.session_state.get("quantlab_pending_sync_request")
    pending_summary = st.session_state.get("quantlab_pending_sync_summary")

    if pending_request is None:
        st.info("Submit the form above to prepare a request draft.")
    else:
        st.json(pending_summary)
        with st.expander("Raw request draft", expanded=False):
            st.code(json.dumps(pending_request, indent=2), language="json")

        st.subheader("Execution hook")
        if probe.available:
            st.success(probe.message)
        else:
            st.info(probe.message)

        button_col1, button_col2 = st.columns(2)
        with button_col1:
            dry_run_clicked = st.button(
                "Run dry-run plan",
                type="primary",
                use_container_width=True,
            )
        with button_col2:
            execute_clicked = st.button(
                "Run sync execution",
                type="secondary",
                use_container_width=True,
                disabled=not probe.available,
            )

        if dry_run_clicked:
            with st.spinner("Building dry-run plan..."):
                result = _build_plan(pending_request, sync_paths)
            st.session_state["quantlab_last_sync_execution"] = {
                "action": "dry-run",
                "workflow": str(pending_request.get("workflow", "")),
                "success": bool(result.get("success", False)),
                "message": str(result.get("message", "")),
                "payload": result.get("payload"),
                "error": result.get("error"),
                "next_steps": result.get("next_steps", []),
                "error_type": result.get("error_type"),
            }

        if execute_clicked:
            with st.spinner("Running sync execution..."):
                execution = execute_sync_request(pending_request, root=ROOT)
            execution_payload = _to_jsonish(execution.payload)
            next_steps = []
            error = None
            if isinstance(execution_payload, dict):
                raw_next_steps = execution_payload.get("next_steps")
                if isinstance(raw_next_steps, list):
                    next_steps = [str(step) for step in raw_next_steps]
                raw_error = execution_payload.get("error")
                if raw_error is not None:
                    error = str(raw_error)
            st.session_state["quantlab_last_sync_execution"] = {
                "action": "execute",
                "workflow": str(pending_request.get("workflow", "")),
                "success": bool(execution.success),
                "message": execution.message,
                "payload": execution_payload,
                "artifact_path": execution.artifact_path,
                "sync_run_id": execution.sync_run_id,
                "next_steps": next_steps,
                "error": error,
            }

last_execution = st.session_state.get("quantlab_last_sync_execution")
if last_execution is not None:
    st.divider()
    st.subheader("Latest execution result")
    if last_execution.get("success"):
        st.success(str(last_execution.get("message", "")))
    else:
        st.warning(str(last_execution.get("message", "")))
    st.json(last_execution)
    payload = last_execution.get("payload")
    if payload is not None:
        with st.expander("Rendered result payload", expanded=False):
            _render_payload(payload)
    error = last_execution.get("error")
    if error:
        with st.expander("Execution error", expanded=False):
            st.code(str(error))
    next_steps = last_execution.get("next_steps")
    if isinstance(next_steps, list) and next_steps:
        st.markdown("**Suggested next steps**")
        for step in next_steps:
            st.markdown(f"- {step}")

st.divider()
st.subheader("Recent saved sync runs")
recent_runs = load_recent_sync_runs(limit=12, root=ROOT)
if not recent_runs:
    st.info("No persisted sync runs are available yet.")
else:
    run_frame = pd.DataFrame(
        [
            {
                "sync_run_id": run.sync_run_id,
                "workflow": run.workflow,
                "status": str(run.status),
                "requested_at": run.requested_at.isoformat(sep=" ") if run.requested_at else "",
                "completed_at": run.completed_at.isoformat(sep=" ") if run.completed_at else "",
                "source": run.source_label,
            }
            for run in recent_runs
        ]
    )
    st.dataframe(run_frame, use_container_width=True, hide_index=True)
    selected_run_id = st.selectbox(
        "Sync run ID",
        options=[run.sync_run_id for run in recent_runs],
    )
    selected_summary = next(run for run in recent_runs if run.sync_run_id == selected_run_id)
    st.caption(f"Loaded from `{selected_summary.artifact_dir}` via {selected_summary.source_label}.")

    artifact = load_sync_run_artifact_from_sources(selected_run_id, root=ROOT)
    if artifact is None:
        st.warning("The selected run does not have saved artifact files yet.")
    else:
        if artifact.manifest is not None:
            with st.expander("Artifact manifest", expanded=False):
                st.json(_to_jsonish(artifact.manifest))
        with st.expander("Saved request", expanded=False):
            _render_payload(artifact.request_payload)
        with st.expander("Saved summary", expanded=True):
            _render_payload(artifact.summary_payload)
        if artifact.validation_payload is not None:
            with st.expander("Saved validation", expanded=False):
                _render_payload(artifact.validation_payload)
        else:
            st.info("No saved validation artifact was found for this run.")
