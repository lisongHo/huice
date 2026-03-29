from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.ui.data_access import is_passing_validation_status, load_home_page_data  # noqa: E402
from app.ui.theme import (  # noqa: E402
    apply_workbench_theme,
    execution_mode_label,
    render_card,
    render_page_header,
    render_section_label,
    run_status_label,
    source_label,
)

apply_workbench_theme("量化研究工作台")


def _format_pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2%}"


def _run_frame(runs: list) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "run_id": run.run_id,
                "策略": run.strategy_name,
                "区间": f"{run.start_date} 至 {run.end_date}",
                "执行模式": execution_mode_label(run.execution_mode),
                "状态": run_status_label(str(run.status)),
                "来源": source_label(run.source_label),
                "收益率": run.total_return_pct,
                "最大回撤": run.max_drawdown_pct,
                "成交笔数": run.trade_count,
            }
            for run in runs
        ]
    )


home = load_home_page_data(limit=12)
latest_run = home.recent_runs[0] if home.recent_runs else None
completed_runs = [run for run in home.recent_runs if str(run.status).lower() == "completed"]

render_page_header(
    kicker="Quantlab v0.1",
    title="量化研究工作台",
    description="中文优先的本地 A 股分钟级研究终端。所有回测、扫描与同步都保持显式触发，artifact 与 run 结果优先展示。",
    badge="单用户 · 本机使用",
)

readiness = home.readiness_summary
if readiness.status == "success":
    st.success(f"{readiness.headline} {readiness.body}")
elif readiness.status == "warning":
    st.warning(f"{readiness.headline} {readiness.body}")
else:
    st.info(f"{readiness.headline} {readiness.body}")
if readiness.next_steps:
    st.markdown("**下一步建议**")
    for step in readiness.next_steps:
        st.markdown(f"- {step}")

metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)
with metric_col1:
    render_card(label="近期运行", value=str(len(home.recent_runs)), note="最近可浏览的回测运行数量")
with metric_col2:
    render_card(label="已完成", value=str(len(completed_runs)), note="状态为 completed 的运行")
with metric_col3:
    render_card(label="本地运行", value=str(home.app_run_count), note="保存到 app/.quantlab 的运行")
with metric_col4:
    render_card(label="扫描批次", value=str(len(home.scan_batches)), note="已保存的参数扫描批次")

focus_col1, focus_col2, focus_col3 = st.columns(3)
with focus_col1:
    render_section_label("今日焦点")
    st.subheader("最近一次运行")
    if latest_run is None:
        st.info("当前还没有可浏览的已保存运行。")
    else:
        st.write(f"`{latest_run.run_id}` · {source_label(latest_run.source_label)}")
        st.write(f"策略：`{latest_run.strategy_name}`")
        st.write(f"区间：{latest_run.start_date} 至 {latest_run.end_date}")
        st.write(f"收益率：{_format_pct(latest_run.total_return_pct)}")
with focus_col2:
    render_section_label("默认模板")
    st.subheader("内置策略模板")
    st.write(f"策略：`{home.default_template.strategy_name}`")
    st.write(f"执行：`{execution_mode_label(home.default_template.execution_mode)}`")
    st.caption(home.default_template.notes)
    if home.latest_saved_template is not None:
        st.write("最近一次可复用模板")
        st.write(
            f"`{home.latest_saved_template.strategy_name}` "
            f"（{home.latest_saved_template.start_date} 至 {home.latest_saved_template.end_date}）"
        )
with focus_col3:
    render_section_label("数据健康")
    st.subheader("校验概览")
    st.write(home.data_health_note)
    if home.validation_summary is None:
        st.info("当前还没有可用的校验摘要。")
    else:
        failing = home.validation_summary.recent_results
        failing = failing[~failing["status"].astype(str).str.lower().map(is_passing_validation_status)]
        st.metric("近期异常", len(failing))
        st.metric("共享运行", home.shared_run_count)

st.divider()
left_col, right_col = st.columns((1.6, 1))
with left_col:
    render_section_label("运行目录")
    st.subheader("近期回测目录")
    run_frame = _run_frame(home.recent_runs)
    if run_frame.empty:
        st.info("当前还没有可浏览的运行目录。")
    else:
        st.dataframe(run_frame, use_container_width=True, hide_index=True)
with right_col:
    render_section_label("扫描结果")
    st.subheader("参数扫描批次")
    if not home.scan_batches:
        st.info("当前还没有已保存的扫描批次。")
    else:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "批次 ID": batch.scan_batch_id,
                        "策略": batch.strategy_name,
                        "运行数": batch.run_count,
                        "最佳收益率": batch.best_return_pct,
                        "来源": source_label(batch.source_label),
                    }
                    for batch in home.scan_batches
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )

st.divider()
library_col, validation_col = st.columns((1, 1.4))
with library_col:
    render_section_label("研究目录")
    st.subheader("实验资料库")
    if not home.experiment_library_entries:
        st.info("`app/**` 下还没有实验资料结构。")
    else:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "标签": entry.label,
                        "类型": entry.kind,
                        "条目数": entry.item_count,
                        "更新时间": entry.modified_at,
                    }
                    for entry in home.experiment_library_entries
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )
with validation_col:
    render_section_label("校验记录")
    st.subheader("近期校验检查")
    if not home.validation_results:
        st.info("当前还没有可用的校验结果。")
    else:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "数据集": item.dataset_name,
                        "检查项": item.check_name,
                        "严重级别": item.severity,
                        "状态": item.status,
                        "详情": item.details,
                    }
                    for item in home.validation_results
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )

st.divider()
render_section_label("状态目录")
st.subheader("本地状态路由")
state_snapshot = {
    "workspace_root": str(home.app_paths.workspace_root),
    "app_local_state_dir": str(home.app_paths.local_state_dir),
    "app_runs_root": str(home.app_paths.runs_root),
    "shared_registry_path": str(home.shared_paths.registry_path),
    "shared_lake_root": str(home.shared_paths.lake_root),
}
st.code(json.dumps(state_snapshot, indent=2), language="json")
