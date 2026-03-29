from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quantlab.schemas import BacktestRunConfig  # noqa: E402

from app.ui.charts import (  # noqa: E402
    annual_returns_figure,
    drawdown_figure,
    equity_curve_figure,
    trade_table_frame,
)
from app.ui.data_access import (  # noqa: E402
    build_run_submission,
    default_template_summary,
    load_recent_runs_catalog,
    load_run_artifacts_from_sources,
)
from app.ui.forms import render_single_backtest_form  # noqa: E402
from app.ui.theme import (  # noqa: E402
    apply_workbench_theme,
    execution_mode_label,
    render_page_header,
    render_section_label,
    run_status_label,
    source_label,
)
from app.ui.workbench import execute_backtest_run  # noqa: E402


apply_workbench_theme("单次回测")
default_config = default_template_summary().config

render_page_header(
    kicker="Single Backtest",
    title="单次回测",
    description="先准备一次完整的 run request，再显式执行。已保存的 artifact 永远优先展示，不会因为页面操作而自动重算。",
    badge="显式执行",
)

draft = render_single_backtest_form(default_config)
if draft.submitted:
    if draft.config is None:
        st.session_state["quantlab_pending_backtest_request"] = draft.payload
        st.session_state["quantlab_pending_backtest_summary"] = draft.summary
    else:
        submission = build_run_submission(draft.config, run_requested=False)
        st.session_state["quantlab_pending_backtest_request"] = submission.payload
        st.session_state["quantlab_pending_backtest_summary"] = draft.summary
    st.success("回测请求已准备完成。在你点击执行按钮之前，系统保持空闲。")

pending_request = st.session_state.get("quantlab_pending_backtest_request")
pending_summary = st.session_state.get("quantlab_pending_backtest_summary")

control_col1, control_col2 = st.columns((1.5, 1))
with control_col1:
    render_section_label("请求草稿")
    st.subheader("已准备的回测请求")
    if pending_request is None:
        st.info("先提交上方配置表单，生成一份可执行的 request 快照。")
    else:
        if pending_summary is not None:
            st.json(pending_summary)
        with st.expander("查看原始 request payload", expanded=False):
            st.code(json.dumps(pending_request, indent=2), language="json")
with control_col2:
    render_section_label("执行入口")
    st.subheader("回测执行")
    seed_demo_if_missing = st.checkbox(
        "若本地没有行情数据，则写入 demo 数据到 app-local state",
        value=True,
        help="只会写入 app/.quantlab，并且仅在点击执行按钮后触发。",
    )
    run_now = st.button(
        "立即执行回测",
        type="primary",
        disabled=pending_request is None,
        use_container_width=True,
    )
    if run_now and pending_request is not None:
        config = BacktestRunConfig.model_validate(pending_request)
        with st.spinner("Executing backtest and persisting artifacts..."):
            execution = execute_backtest_run(config, seed_demo_if_missing=seed_demo_if_missing)
        st.session_state["quantlab_last_backtest_execution"] = {
            "success": execution.success,
            "run_id": execution.run_id,
            "message": execution.message,
            "manifest": None if execution.manifest is None else execution.manifest.model_dump(mode="json"),
            "metrics": execution.metrics,
            "used_seed_demo": execution.used_seed_demo,
            "paths": {
                "local_state_dir": str(execution.paths.local_state_dir),
                "runs_root": str(execution.paths.runs_root),
                "lake_root": str(execution.paths.lake_root),
            },
        }

last_execution = st.session_state.get("quantlab_last_backtest_execution")
if last_execution is not None:
    st.divider()
    render_section_label("执行结果")
    st.subheader("最近一次执行")
    if last_execution["success"]:
        st.success(last_execution["message"])
    else:
        st.error(last_execution["message"])
    st.json(last_execution)

st.divider()
render_section_label("结果浏览")
st.subheader("已完成回测")
recent_runs = load_recent_runs_catalog(limit=30)
run_ids = [run.run_id for run in recent_runs]
selected_run_id = st.query_params.get("run_id")
if not isinstance(selected_run_id, str) or selected_run_id not in run_ids:
    selected_run_id = run_ids[0] if run_ids else None

if not recent_runs:
    st.info("当前还没有已保存的回测结果。")
elif selected_run_id is None:
    st.info("当前没有可选中的 run。")
else:
    selected_run_id = st.selectbox("Run ID", options=run_ids, index=run_ids.index(selected_run_id))
    summary = next(run for run in recent_runs if run.run_id == selected_run_id)
    artifacts = load_run_artifacts_from_sources(selected_run_id)

    meta_col1, meta_col2 = st.columns((1.5, 1))
    with meta_col1:
        st.write(
            f"策略 `{summary.strategy_name}` · 区间 {summary.start_date} 至 {summary.end_date} · "
            f"执行模式 `{execution_mode_label(summary.execution_mode)}`"
        )
        st.caption(f"已从 `{source_label(artifacts.source_label)}` 的 artifacts 加载。")
    with meta_col2:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "状态": run_status_label(str(summary.status)),
                        "来源": source_label(summary.source_label),
                        "收益率": summary.total_return_pct,
                        "最大回撤": summary.max_drawdown_pct,
                        "成交笔数": summary.trade_count,
                    }
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )

    if artifacts.metrics:
        metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)
        with metric_col1:
            st.metric("总收益", f"{float(artifacts.metrics.get('total_return_pct', 0.0)):.2%}")
        with metric_col2:
            st.metric("最大回撤", f"{float(artifacts.metrics.get('max_drawdown_pct', 0.0)):.2%}")
        with metric_col3:
            st.metric("胜率", f"{float(artifacts.metrics.get('win_rate_pct', 0.0)):.2%}")
        with metric_col4:
            st.metric("成交笔数", int(artifacts.metrics.get("trade_count", 0)))

    chart_col1, chart_col2 = st.columns(2)
    with chart_col1:
        st.plotly_chart(equity_curve_figure(artifacts.equity_curve), use_container_width=True)
    with chart_col2:
        st.plotly_chart(drawdown_figure(artifacts.drawdown_curve), use_container_width=True)

    st.plotly_chart(annual_returns_figure(artifacts.annual_returns), use_container_width=True)

    st.subheader("成交明细表")
    trades = trade_table_frame(artifacts.trades)
    if trades.empty:
        st.info("该 run 目前还没有可展示的成交账本。")
    else:
        st.dataframe(trades, use_container_width=True, hide_index=True)

    with st.expander("查看原始 artifacts", expanded=False):
        st.write("Manifest")
        if artifacts.manifest is None:
            st.info("没有找到 manifest 文件。")
        else:
            st.json(artifacts.manifest.model_dump(mode="json"))
        st.write("Metrics")
        st.code(json.dumps(artifacts.metrics or {}, indent=2), language="json")
