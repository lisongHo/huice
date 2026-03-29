from __future__ import annotations

import json
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.ui.data_access import load_latest_readiness_artifact  # noqa: E402
from app.ui.theme import apply_workbench_theme, render_page_header, render_section_label  # noqa: E402
from app.ui.workbench import detect_provider_readiness_runner, execute_provider_readiness_check  # noqa: E402


apply_workbench_theme("数据源就绪检查")


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
        st.markdown("**下一步建议**")
        for step in next_steps:
            st.markdown(f"- {step}")


render_page_header(
    kicker="Provider Readiness",
    title="数据源就绪检查",
    description="先读取最近一次已保存的 readiness artifact，再决定是否重新检查。所有检查都只会在你点击按钮后执行。",
    badge="显式检查",
)

latest_artifact = load_latest_readiness_artifact()
probe = detect_provider_readiness_runner()

overview_col, action_col = st.columns((1.4, 1))
with overview_col:
    render_section_label("已保存结果")
    st.subheader("最近一次就绪检查")
    if latest_artifact is None:
        st.info("当前还没有已保存的 readiness artifact。")
    else:
        st.caption(f"已从 `{latest_artifact.path}` 加载。")
        _render_summary(latest_artifact.summary)
        with st.expander("查看原始 artifact", expanded=False):
            payload = getattr(latest_artifact, "payload", None)
            if isinstance(payload, dict):
                st.code(json.dumps(payload, indent=2), language="json")
            elif isinstance(payload, list):
                st.code(json.dumps(payload, indent=2), language="json")
            elif payload is None:
                st.info("该 artifact 没有可直接展示的原始 payload。")
            else:
                st.code(str(payload))

with action_col:
    render_section_label("执行入口")
    st.subheader("重新执行检查")
    if probe.available:
        st.success(probe.message)
    else:
        st.info(probe.message)
    st.write("系统不会自动运行检查；只有点击按钮时才会触发。")
    run_now = st.button(
        "立即执行就绪检查",
        type="primary",
        use_container_width=True,
        disabled=not probe.available,
    )
    if run_now:
        with st.spinner("正在执行数据源就绪检查..."):
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
    render_section_label("最近执行")
    st.subheader("最近一次检查结果")
    if last_execution["success"]:
        st.success(last_execution["message"])
    else:
        st.warning(last_execution["message"])
    st.json(last_execution)
