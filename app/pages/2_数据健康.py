from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.ui.data_access import load_data_health_snapshot  # noqa: E402
from app.ui.theme import apply_workbench_theme, render_page_header, render_section_label  # noqa: E402


apply_workbench_theme("数据健康")
snapshot = load_data_health_snapshot()

render_page_header(
    kicker="Data Health",
    title="数据健康",
    description="只读浏览已保存的 validation、dataset registry 与 provider capability 结果，帮助你快速判断当前数据是否可研究。",
    badge="只读视图",
)

metric_col1, metric_col2, metric_col3 = st.columns(3)
with metric_col1:
    st.metric("校验样本", len(snapshot.validation_results))
with metric_col2:
    st.metric("已追踪数据集", len(snapshot.file_manifest))
with metric_col3:
    st.metric("已登记 Provider", len(snapshot.provider_capabilities))

st.info(snapshot.note)

summary_col1, summary_col2 = st.columns(2)
with summary_col1:
    render_section_label("校验总览")
    st.subheader("状态分布")
    if snapshot.validation_summary is None:
        st.info("当前还没有可用的校验摘要。")
    else:
        st.dataframe(snapshot.validation_summary.status_counts, use_container_width=True, hide_index=True)
with summary_col2:
    render_section_label("严重级别")
    st.subheader("严重级别分布")
    if snapshot.validation_summary is None:
        st.info("当前还没有可用的校验摘要。")
    else:
        st.dataframe(snapshot.validation_summary.severity_counts, use_container_width=True, hide_index=True)

detail_col1, detail_col2 = st.columns((1.2, 1))
with detail_col1:
    render_section_label("明细记录")
    st.subheader("近期校验检查")
    if not snapshot.validation_results:
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
                    for item in snapshot.validation_results
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )
with detail_col2:
    render_section_label("文件落盘")
    st.subheader("数据集文件")
    if not snapshot.file_manifest:
        st.info("当前还没有 file-manifest 记录。")
    else:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "数据集": item.dataset_name,
                        "文件数": item.file_count,
                        "行数": item.row_count,
                    }
                    for item in snapshot.file_manifest
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )

render_section_label("数据源能力")
st.subheader("Provider capabilities")
if not snapshot.provider_capabilities:
    st.info("当前还没有 provider capability 记录。")
else:
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Provider": item.provider_name,
                    "分钟线": item.supports_minute_bars,
                    "状态历史": item.supports_security_status_history,
                    "涨跌停": item.supports_price_limits,
                    "停牌": item.supports_suspensions,
                }
                for item in snapshot.provider_capabilities
            ]
        ),
        use_container_width=True,
        hide_index=True,
    )
