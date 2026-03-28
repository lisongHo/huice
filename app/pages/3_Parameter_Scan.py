from __future__ import annotations

import json
import sys
from itertools import product
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.ui.charts import scan_comparison_figure  # noqa: E402
from app.ui.data_access import (  # noqa: E402
    default_template_summary,
    load_scan_batch_result_from_sources,
    load_scan_batches,
)
from app.ui.forms import render_parameter_scan_form  # noqa: E402
from app.ui.workbench import detect_scan_runner, execute_parameter_scan  # noqa: E402


st.set_page_config(page_title="Parameter Scan", layout="wide")


def _scan_run_frame(batch) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "run_id": run.run_id,
                **run.params,
                "total_return_pct": run.total_return_pct,
                "max_drawdown_pct": run.max_drawdown_pct,
                "trade_count": run.trade_count,
                "annualized_return_pct": run.annualized_return_pct,
            }
            for run in batch.runs
        ]
    )


default_config = default_template_summary().config
probe = detect_scan_runner()

st.title("Parameter Scan")
st.caption("Prepare scan grids explicitly, browse persisted batches, and only execute when a scan hook is available.")

draft = render_parameter_scan_form(default_config)
if draft.submitted:
    st.session_state["quantlab_pending_scan_request"] = draft.payload
    st.session_state["quantlab_pending_scan_summary"] = draft.summary
    st.success("Scan request prepared. Nothing runs until you click the scan button.")

pending_request = st.session_state.get("quantlab_pending_scan_request")
pending_summary = st.session_state.get("quantlab_pending_scan_summary")

prep_col1, prep_col2 = st.columns((1.4, 1))
with prep_col1:
    st.subheader("Prepared scan request")
    if pending_request is None:
        st.info("Submit the form above to prepare a scan request payload.")
    else:
        st.json(pending_summary)
        combination_count = len(
            list(
                product(
                    pending_request["grid"]["consecutive_down_days"],
                    pending_request["grid"]["rsi_threshold"],
                    pending_request["grid"]["hold_days"],
                )
            )
        )
        st.caption(f"Grid size: {combination_count} parameter combinations.")
        with st.expander("Raw scan request", expanded=False):
            st.code(json.dumps(pending_request, indent=2), language="json")
with prep_col2:
    st.subheader("Execution hook")
    if probe.available:
        st.success(probe.message)
    else:
        st.info(probe.message)
    seed_demo_if_missing = st.checkbox(
        "Seed demo data into app-local state if required for scan execution",
        value=False,
    )
    run_scan = st.button(
        "Run parameter scan",
        type="primary",
        use_container_width=True,
        disabled=(pending_request is None or not probe.available),
    )
    if run_scan and pending_request is not None:
        with st.spinner("Executing parameter scan..."):
            execution = execute_parameter_scan(
                pending_request,
                seed_demo_if_missing=seed_demo_if_missing,
            )
        st.session_state["quantlab_last_scan_execution"] = {
            "success": execution.success,
            "message": execution.message,
            "used_seed_demo": execution.used_seed_demo,
            "batch": None if execution.batch is None else execution.batch.model_dump(mode="json"),
        }

last_execution = st.session_state.get("quantlab_last_scan_execution")
if last_execution is not None:
    st.divider()
    if last_execution["success"]:
        st.success(last_execution["message"])
    else:
        st.warning(last_execution["message"])
    st.json(last_execution)

st.divider()
st.subheader("Persisted scan batches")
batches = load_scan_batches(limit=20)
if not batches:
    st.info("No persisted scan batches are available yet.")
else:
    batch_ids = [batch.scan_batch_id for batch in batches]
    selected_batch_id = st.selectbox("Scan batch ID", options=batch_ids)
    batch_summary = next(batch for batch in batches if batch.scan_batch_id == selected_batch_id)
    batch = load_scan_batch_result_from_sources(selected_batch_id)

    st.dataframe(
        pd.DataFrame(
            [
                {
                    "scan_batch_id": batch_summary.scan_batch_id,
                    "strategy": batch_summary.strategy_name,
                    "runs": batch_summary.run_count,
                    "parameters": ", ".join(batch_summary.parameter_names),
                    "best_run_id": batch_summary.best_run_id,
                    "best_return_pct": batch_summary.best_return_pct,
                    "source": batch_summary.source_label,
                }
            ]
        ),
        use_container_width=True,
        hide_index=True,
    )

    if batch is None:
        st.warning("The selected scan batch metadata exists, but its result payload could not be loaded.")
    else:
        run_frame = _scan_run_frame(batch)
        st.plotly_chart(scan_comparison_figure(run_frame), use_container_width=True)
        st.dataframe(run_frame, use_container_width=True, hide_index=True)
