from __future__ import annotations

import json
import sys
from dataclasses import is_dataclass
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.ui.data_access import load_latest_saved_readiness_summary  # noqa: E402
from app.ui.forms import render_sync_cockpit_form  # noqa: E402
from app.ui.workbench import build_shared_paths  # noqa: E402
from data.providers.tushare_readiness import (  # noqa: E402
    classify_tushare_planning_blocker,
    format_tushare_planning_blocker,
)
from data.ingest.sync import build_backfill_plan, build_refresh_plan, sync_plan_to_dict  # noqa: E402


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


def _plan_to_payload(plan: object) -> dict[str, object]:
    if hasattr(plan, "model_dump"):
        return dict(plan.model_dump(mode="json"))  # type: ignore[call-arg]
    if is_dataclass(plan):
        return sync_plan_to_dict(plan)  # type: ignore[arg-type]
    if isinstance(plan, dict):
        return plan
    return {"value": plan}


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
                "plan": _plan_to_payload(plan),
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
            "plan": _plan_to_payload(plan),
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
st.caption("Prepare a dry-run sync request, then execute planning only when you click the button.")

latest_readiness = load_latest_saved_readiness_summary()
sync_paths = build_shared_paths(ROOT)

overview_col, action_col = st.columns((1.25, 1))
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

with action_col:
    st.subheader("Dry-run planning")
    draft = render_sync_cockpit_form()
    if draft.submitted:
        st.session_state["quantlab_pending_sync_request"] = draft.payload
        st.session_state["quantlab_pending_sync_summary"] = draft.summary
        st.success("Dry-run request prepared. Nothing runs until you click the planning button.")

    pending_request = st.session_state.get("quantlab_pending_sync_request")
    pending_summary = st.session_state.get("quantlab_pending_sync_summary")

    if pending_request is None:
        st.info("Prepare a request above to enable explicit dry-run planning.")
    else:
        if pending_summary is not None:
            st.json(pending_summary)
        run_now = st.button(
            "Run dry-run plan now",
            type="primary",
            use_container_width=True,
        )
        if run_now:
            with st.spinner("Building dry-run plan..."):
                result = _build_plan(pending_request, sync_paths)
            st.session_state["quantlab_last_sync_execution"] = result

last_execution = st.session_state.get("quantlab_last_sync_execution")
if last_execution is not None:
    st.divider()
    st.subheader("Latest dry-run result")
    if last_execution.get("success"):
        st.success(last_execution["message"])
        st.json(last_execution.get("plan", {}))
    else:
        st.error(last_execution["message"])
        next_steps = last_execution.get("next_steps")
        if isinstance(next_steps, list) and next_steps:
            st.markdown("**Suggested next steps**")
            for step in next_steps:
                st.markdown(f"- {step}")
        if last_execution.get("error"):
            st.code(str(last_execution["error"]))
