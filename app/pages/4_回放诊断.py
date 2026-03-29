from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.ui.charts import (  # noqa: E402
    drawdown_figure,
    equity_curve_figure,
    event_window_figure,
    trade_table_frame,
)
from app.ui.data_access import load_recent_runs_catalog, load_run_artifacts_from_sources  # noqa: E402
from app.ui.theme import apply_workbench_theme, execution_mode_label, render_page_header, render_section_label, run_status_label, source_label  # noqa: E402


apply_workbench_theme("回放诊断")


def _trade_label(row: pd.Series) -> str:
    return (
        f"{row.get('trade_date', 'n/a')} | "
        f"{row.get('symbol', 'n/a')} | "
        f"{str(row.get('side', 'n/a')).upper()} | "
        f"{row.get('shares', 'n/a')} @ {row.get('price', 'n/a')}"
    )


def _symbol_summary(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "symbol" not in frame.columns:
        return pd.DataFrame()
    grouped = (
        frame.groupby("symbol", dropna=False)
        .agg(
            trade_count=("symbol", "size"),
            total_amount=("amount", "sum"),
            total_fees=("fees", "sum"),
            first_trade=("trade_date", "min"),
            last_trade=("trade_date", "max"),
        )
        .reset_index()
        .sort_values(["trade_count", "symbol"], ascending=[False, True])
    )
    return grouped


render_page_header(
    kicker="Replay Diagnostics",
    title="回放诊断",
    description="围绕单个 run、单个 symbol 或单笔 trade 进行复盘。优先使用已保存的 equity curve、trade ledger 与 artifacts，不触发额外重算。",
    badge="复盘视图",
)

runs = load_recent_runs_catalog(limit=30)
if not runs:
    st.info("当前还没有已保存的回测结果。")
    st.stop()

run_ids = [run.run_id for run in runs]
selected_run_id = st.selectbox("Run ID", options=run_ids)
summary = next(run for run in runs if run.run_id == selected_run_id)
artifacts = load_run_artifacts_from_sources(selected_run_id)

st.dataframe(
    pd.DataFrame(
        [
            {
                "run_id": summary.run_id,
                "策略": summary.strategy_name,
                "区间": f"{summary.start_date} 至 {summary.end_date}",
                "执行模式": execution_mode_label(summary.execution_mode),
                "状态": run_status_label(str(summary.status)),
                "来源": source_label(artifacts.source_label),
                "收益率": summary.total_return_pct,
                "最大回撤": summary.max_drawdown_pct,
                "成交笔数": summary.trade_count,
            }
        ]
    ),
    use_container_width=True,
    hide_index=True,
)

overview_col1, overview_col2 = st.columns(2)
with overview_col1:
    st.plotly_chart(equity_curve_figure(artifacts.equity_curve), use_container_width=True)
with overview_col2:
    st.plotly_chart(drawdown_figure(artifacts.drawdown_curve), use_container_width=True)

trades = trade_table_frame(artifacts.trades)
if trades.empty:
    st.info("该 run 还没有可用的成交账本，回放诊断暂时停留在 run 级图表。")
    with st.expander("查看原始 artifacts", expanded=False):
        st.code(json.dumps(artifacts.metrics or {}, indent=2), language="json")
    st.stop()

symbol_options = ["全部 symbols"]
if "symbol" in trades.columns:
    symbol_options.extend(sorted(trades["symbol"].dropna().astype(str).unique().tolist()))
selected_symbol = st.selectbox("聚焦 symbol", options=symbol_options)
filtered_trades = trades if selected_symbol == "全部 symbols" else trades[trades["symbol"].astype(str) == selected_symbol]

symbol_col1, symbol_col2 = st.columns((1, 1.2))
with symbol_col1:
    render_section_label("Symbol 维度")
    st.subheader("Symbol 汇总")
    symbol_frame = _symbol_summary(filtered_trades if selected_symbol != "全部 symbols" else trades)
    if symbol_frame.empty:
        st.info("当前没有可用的 symbol 汇总。")
    else:
        st.dataframe(
            symbol_frame.rename(
                columns={
                    "symbol": "symbol",
                    "trade_count": "成交笔数",
                    "total_amount": "总成交额",
                    "total_fees": "总费用",
                    "first_trade": "首次成交日",
                    "last_trade": "最后成交日",
                }
            ),
            use_container_width=True,
            hide_index=True,
        )
with symbol_col2:
    render_section_label("成交筛选")
    st.subheader("筛选后的成交账本")
    st.dataframe(filtered_trades, use_container_width=True, hide_index=True)

trade_labels = [_trade_label(row) for _, row in filtered_trades.iterrows()]
selected_trade_label = st.selectbox("聚焦 trade", options=trade_labels)
selected_trade = filtered_trades.iloc[trade_labels.index(selected_trade_label)]
trade_date = selected_trade.get("trade_date")

if artifacts.equity_curve.empty:
    equity_window = pd.DataFrame()
else:
    equity_curve = artifacts.equity_curve.copy()
    equity_curve["trade_date"] = pd.to_datetime(equity_curve["trade_date"]).dt.date
    if trade_date is None:
        equity_window = equity_curve.tail(9)
    else:
        matching = equity_curve.index[equity_curve["trade_date"] == trade_date].tolist()
        if matching:
            anchor = matching[0]
            equity_window = equity_curve.iloc[max(anchor - 4, 0) : anchor + 5]
        else:
            equity_window = equity_curve.tail(9)

diag_col1, diag_col2 = st.columns((1.2, 1))
with diag_col1:
    render_section_label("事件窗口")
    st.subheader("围绕成交的权益曲线窗口")
    st.plotly_chart(
        event_window_figure(
            equity_window,
            event_date=trade_date,
            title="Equity around selected trade",
        ),
        use_container_width=True,
    )
with diag_col2:
    render_section_label("成交详情")
    st.subheader("选中 trade 明细")
    st.json({key: value for key, value in selected_trade.to_dict().items()})
