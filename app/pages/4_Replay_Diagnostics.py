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


st.set_page_config(page_title="Replay Diagnostics", layout="wide")


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


st.title("Replay Diagnostics")
st.caption("Artifact-first diagnostics for one run, one symbol, or one trade whenever saved trades and equity curves exist.")

runs = load_recent_runs_catalog(limit=30)
if not runs:
    st.info("No persisted runs are available yet.")
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
                "strategy": summary.strategy_name,
                "window": f"{summary.start_date} to {summary.end_date}",
                "mode": summary.execution_mode,
                "status": str(summary.status),
                "source": artifacts.source_label,
                "return_pct": summary.total_return_pct,
                "max_dd_pct": summary.max_drawdown_pct,
                "trades": summary.trade_count,
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
    st.info("No saved trade ledger exists for this run yet, so replay diagnostics stop at run-level charts.")
    with st.expander("Raw artifacts", expanded=False):
        st.code(json.dumps(artifacts.metrics or {}, indent=2), language="json")
    st.stop()

symbol_options = ["All symbols"]
if "symbol" in trades.columns:
    symbol_options.extend(sorted(trades["symbol"].dropna().astype(str).unique().tolist()))
selected_symbol = st.selectbox("Symbol focus", options=symbol_options)
filtered_trades = trades if selected_symbol == "All symbols" else trades[trades["symbol"].astype(str) == selected_symbol]

symbol_col1, symbol_col2 = st.columns((1, 1.2))
with symbol_col1:
    st.subheader("Symbol rollup")
    symbol_frame = _symbol_summary(filtered_trades if selected_symbol != "All symbols" else trades)
    if symbol_frame.empty:
        st.info("No symbol summary is available.")
    else:
        st.dataframe(symbol_frame, use_container_width=True, hide_index=True)
with symbol_col2:
    st.subheader("Filtered trade ledger")
    st.dataframe(filtered_trades, use_container_width=True, hide_index=True)

trade_labels = [_trade_label(row) for _, row in filtered_trades.iterrows()]
selected_trade_label = st.selectbox("Trade focus", options=trade_labels)
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
    st.subheader("Trade-centered equity window")
    st.plotly_chart(
        event_window_figure(
            equity_window,
            event_date=trade_date,
            title="Equity around selected trade",
        ),
        use_container_width=True,
    )
with diag_col2:
    st.subheader("Trade detail")
    st.json({key: value for key, value in selected_trade.to_dict().items()})
