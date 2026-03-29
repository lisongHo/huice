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
from app.ui.theme import (  # noqa: E402
    apply_workbench_theme,
    render_page_header,
    render_section_label,
    run_status_label,
    source_label,
    workflow_label,
)
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


apply_workbench_theme("同步驾驶舱")


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
        st.markdown("**下一步建议**")
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
        st.info("该运行当前没有可展示的已保存 payload。")
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
                "message": "Backfill dry-run 规划已生成。",
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
            "message": f"{_workflow_label(workflow)} dry-run 规划已生成。",
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
            "message": f"{_workflow_label(workflow)} dry-run 规划失败：{exc}",
            "error": str(exc),
        }


render_page_header(
    kicker="Sync Cockpit",
    title="同步驾驶舱",
    description=(
        "先准备同步请求，再选择 dry-run 规划或真实执行。即使 runner hook 暂不可用，"
        "也可以继续浏览 readiness 与已保存的 sync runs。"
    ),
    badge="手动触发",
)

latest_readiness = load_latest_saved_readiness_summary()
sync_paths = build_shared_paths(ROOT)
probe = detect_sync_runner()

overview_col, request_col = st.columns((1.25, 1))
with overview_col:
    render_section_label("准备状态")
    st.subheader("最近一次数据源就绪检查")
    if latest_readiness is None:
        st.info("当前还没有已保存的 readiness 摘要。")
    else:
        _render_summary(latest_readiness)
        with st.expander("查看原始 readiness 摘要", expanded=False):
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
    render_section_label("请求草稿")
    st.subheader("准备同步请求")
    draft = render_sync_cockpit_form()
    if draft.submitted:
        st.session_state["quantlab_pending_sync_request"] = draft.payload
        st.session_state["quantlab_pending_sync_summary"] = draft.summary
        st.success("同步请求已准备完成。在你点击按钮前，不会自动执行。")

    pending_request = st.session_state.get("quantlab_pending_sync_request")
    pending_summary = st.session_state.get("quantlab_pending_sync_summary")

    if pending_request is None:
        st.info("先提交上方表单，生成一份同步请求草稿。")
    else:
        st.json(pending_summary)
        with st.expander("查看原始请求草稿", expanded=False):
            st.code(json.dumps(pending_request, indent=2), language="json")

        render_section_label("执行入口")
        st.subheader("同步执行")
        if probe.available:
            st.success(probe.message)
        else:
            st.info(probe.message)

        button_col1, button_col2 = st.columns(2)
        with button_col1:
            dry_run_clicked = st.button(
                "执行 dry-run 规划",
                type="primary",
                use_container_width=True,
            )
        with button_col2:
            execute_clicked = st.button(
                "执行真实同步",
                type="secondary",
                use_container_width=True,
                disabled=not probe.available,
            )

        if dry_run_clicked:
            with st.spinner("正在构建 dry-run 规划..."):
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
            with st.spinner("正在执行真实同步..."):
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
    render_section_label("最近执行")
    st.subheader("最近一次执行结果")
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
        with st.expander("查看错误详情", expanded=False):
            st.code(str(error))
    next_steps = last_execution.get("next_steps")
    if isinstance(next_steps, list) and next_steps:
        st.markdown("**下一步建议**")
        for step in next_steps:
            st.markdown(f"- {step}")

st.divider()
render_section_label("结果浏览")
st.subheader("近期已保存的同步运行")
recent_runs = load_recent_sync_runs(limit=12, root=ROOT)
if not recent_runs:
    st.info("当前还没有已保存的 sync runs。")
else:
    run_frame = pd.DataFrame(
        [
            {
                "sync_run_id": run.sync_run_id,
                "同步模式": workflow_label(run.workflow),
                "状态": run_status_label(str(run.status)),
                "请求时间": run.requested_at.isoformat(sep=" ") if run.requested_at else "",
                "完成时间": run.completed_at.isoformat(sep=" ") if run.completed_at else "",
                "来源": source_label(run.source_label),
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
    st.caption(f"已从 `{selected_summary.artifact_dir}` 载入，来源 `{source_label(selected_summary.source_label)}`。")

    artifact = load_sync_run_artifact_from_sources(selected_run_id, root=ROOT)
    if artifact is None:
        st.warning("该同步运行暂时还没有可读取的 artifact 文件。")
    else:
        if artifact.manifest is not None:
            with st.expander("查看 artifact manifest", expanded=False):
                st.json(_to_jsonish(artifact.manifest))
        with st.expander("查看已保存 request", expanded=False):
            _render_payload(artifact.request_payload)
        with st.expander("查看已保存 summary", expanded=True):
            _render_payload(artifact.summary_payload)
        if artifact.validation_payload is not None:
            with st.expander("查看已保存 validation", expanded=False):
                _render_payload(artifact.validation_payload)
        else:
            st.info("该同步运行没有找到已保存的 validation artifact。")
