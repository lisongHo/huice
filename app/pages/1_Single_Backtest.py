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
from app.ui.workbench import execute_backtest_run  # noqa: E402


st.set_page_config(page_title="Single Backtest", layout="wide")
default_config = default_template_summary().config

st.title("Single Backtest")
st.caption("Prepare one run, then execute it explicitly. Persisted artifacts are always preferred over recomputation.")

draft = render_single_backtest_form(default_config)
if draft.submitted:
    if draft.config is None:
        st.session_state["quantlab_pending_backtest_request"] = draft.payload
        st.session_state["quantlab_pending_backtest_summary"] = draft.summary
    else:
        submission = build_run_submission(draft.config, run_requested=False)
        st.session_state["quantlab_pending_backtest_request"] = submission.payload
        st.session_state["quantlab_pending_backtest_summary"] = draft.summary
    st.success("Run request prepared. Execution remains idle until you click the run button below.")

pending_request = st.session_state.get("quantlab_pending_backtest_request")
pending_summary = st.session_state.get("quantlab_pending_backtest_summary")

control_col1, control_col2 = st.columns((1.5, 1))
with control_col1:
    st.subheader("Prepared request")
    if pending_request is None:
        st.info("Submit the configuration form above to create an executable request snapshot.")
    else:
        if pending_summary is not None:
            st.json(pending_summary)
        with st.expander("Raw request payload", expanded=False):
            st.code(json.dumps(pending_request, indent=2), language="json")
with control_col2:
    st.subheader("Execution")
    seed_demo_if_missing = st.checkbox(
        "Seed demo data into app-local state if no market data is available",
        value=True,
        help="This stays inside app/.quantlab and only runs when the execute button is clicked.",
    )
    run_now = st.button(
        "Run backtest now",
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
    st.subheader("Last execution")
    if last_execution["success"]:
        st.success(last_execution["message"])
    else:
        st.error(last_execution["message"])
    st.json(last_execution)

st.divider()
st.subheader("Completed run results")
recent_runs = load_recent_runs_catalog(limit=30)
run_ids = [run.run_id for run in recent_runs]
selected_run_id = st.query_params.get("run_id")
if not isinstance(selected_run_id, str) or selected_run_id not in run_ids:
    selected_run_id = run_ids[0] if run_ids else None

if not recent_runs:
    st.info("No persisted runs are available yet.")
elif selected_run_id is None:
    st.info("No run is selected.")
else:
    selected_run_id = st.selectbox("Run ID", options=run_ids, index=run_ids.index(selected_run_id))
    summary = next(run for run in recent_runs if run.run_id == selected_run_id)
    artifacts = load_run_artifacts_from_sources(selected_run_id)

    meta_col1, meta_col2 = st.columns((1.5, 1))
    with meta_col1:
        st.write(
            f"Strategy `{summary.strategy_name}` from {summary.start_date} to {summary.end_date} "
            f"using `{summary.execution_mode}`"
        )
        st.caption(f"Loaded from `{artifacts.source_label}` artifacts.")
    with meta_col2:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "status": str(summary.status),
                        "source": summary.source_label,
                        "return_pct": summary.total_return_pct,
                        "max_dd_pct": summary.max_drawdown_pct,
                        "trades": summary.trade_count,
                    }
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )

    if artifacts.metrics:
        metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)
        with metric_col1:
            st.metric("Total return", f"{float(artifacts.metrics.get('total_return_pct', 0.0)):.2%}")
        with metric_col2:
            st.metric("Max drawdown", f"{float(artifacts.metrics.get('max_drawdown_pct', 0.0)):.2%}")
        with metric_col3:
            st.metric("Win rate", f"{float(artifacts.metrics.get('win_rate_pct', 0.0)):.2%}")
        with metric_col4:
            st.metric("Trades", int(artifacts.metrics.get("trade_count", 0)))

    chart_col1, chart_col2 = st.columns(2)
    with chart_col1:
        st.plotly_chart(equity_curve_figure(artifacts.equity_curve), use_container_width=True)
    with chart_col2:
        st.plotly_chart(drawdown_figure(artifacts.drawdown_curve), use_container_width=True)

    st.plotly_chart(annual_returns_figure(artifacts.annual_returns), use_container_width=True)

    st.subheader("Trade table")
    trades = trade_table_frame(artifacts.trades)
    if trades.empty:
        st.info("No trade ledger is available for this run yet.")
    else:
        st.dataframe(trades, use_container_width=True, hide_index=True)

    with st.expander("Raw artifacts", expanded=False):
        st.write("Manifest")
        if artifacts.manifest is None:
            st.info("No manifest file was found.")
        else:
            st.json(artifacts.manifest.model_dump(mode="json"))
        st.write("Metrics")
        st.code(json.dumps(artifacts.metrics or {}, indent=2), language="json")
