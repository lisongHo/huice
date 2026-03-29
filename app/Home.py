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


st.set_page_config(page_title="Quantlab Workbench", layout="wide")


def _format_pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2%}"


def _run_frame(runs: list) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "run_id": run.run_id,
                "strategy": run.strategy_name,
                "window": f"{run.start_date} to {run.end_date}",
                "mode": run.execution_mode,
                "status": str(run.status),
                "source": run.source_label,
                "return_pct": run.total_return_pct,
                "max_dd_pct": run.max_drawdown_pct,
                "trades": run.trade_count,
            }
            for run in runs
        ]
    )


home = load_home_page_data(limit=12)
latest_run = home.recent_runs[0] if home.recent_runs else None
completed_runs = [run for run in home.recent_runs if str(run.status).lower() == "completed"]

st.title("Quantlab Workbench")
st.caption("Artifact-first research console with explicit execution and app-local run persistence.")

readiness = home.readiness_summary
if readiness.status == "success":
    st.success(f"{readiness.headline} {readiness.body}")
elif readiness.status == "warning":
    st.warning(f"{readiness.headline} {readiness.body}")
else:
    st.info(f"{readiness.headline} {readiness.body}")
if readiness.next_steps:
    st.markdown("**Next steps**")
    for step in readiness.next_steps:
        st.markdown(f"- {step}")

metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)
with metric_col1:
    st.metric("Recent runs", len(home.recent_runs))
with metric_col2:
    st.metric("Completed", len(completed_runs))
with metric_col3:
    st.metric("App-local runs", home.app_run_count)
with metric_col4:
    st.metric("Saved scan batches", len(home.scan_batches))

focus_col1, focus_col2, focus_col3 = st.columns(3)
with focus_col1:
    st.subheader("Latest run")
    if latest_run is None:
        st.info("No persisted runs are available yet.")
    else:
        st.write(f"`{latest_run.run_id}` from `{latest_run.source_label}` state")
        st.write(f"Strategy: `{latest_run.strategy_name}`")
        st.write(f"Window: {latest_run.start_date} to {latest_run.end_date}")
        st.write(f"Return: {_format_pct(latest_run.total_return_pct)}")
with focus_col2:
    st.subheader("Template defaults")
    st.write(f"Strategy: `{home.default_template.strategy_name}`")
    st.write(f"Execution: `{home.default_template.execution_mode}`")
    st.caption(home.default_template.notes)
    if home.latest_saved_template is not None:
        st.write("Reusable latest template")
        st.write(
            f"`{home.latest_saved_template.strategy_name}` "
            f"({home.latest_saved_template.start_date} to {home.latest_saved_template.end_date})"
        )
with focus_col3:
    st.subheader("Data health")
    st.write(home.data_health_note)
    if home.validation_summary is None:
        st.info("No validation summary is available yet.")
    else:
        failing = home.validation_summary.recent_results
        failing = failing[~failing["status"].astype(str).str.lower().map(is_passing_validation_status)]
        st.metric("Recent issues", len(failing))
        st.metric("Shared runs", home.shared_run_count)

st.divider()
left_col, right_col = st.columns((1.6, 1))
with left_col:
    st.subheader("Recent run catalog")
    run_frame = _run_frame(home.recent_runs)
    if run_frame.empty:
        st.info("No run catalog entries are available yet.")
    else:
        st.dataframe(run_frame, use_container_width=True, hide_index=True)
with right_col:
    st.subheader("Scan batches")
    if not home.scan_batches:
        st.info("No persisted scan batches are available yet.")
    else:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "scan_batch_id": batch.scan_batch_id,
                        "strategy": batch.strategy_name,
                        "runs": batch.run_count,
                        "best_return_pct": batch.best_return_pct,
                        "source": batch.source_label,
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
    st.subheader("Experiment library")
    if not home.experiment_library_entries:
        st.info("No experiment-library structure exists under app/** yet.")
    else:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "label": entry.label,
                        "kind": entry.kind,
                        "items": entry.item_count,
                        "modified_at": entry.modified_at,
                    }
                    for entry in home.experiment_library_entries
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )
with validation_col:
    st.subheader("Recent validation checks")
    if not home.validation_results:
        st.info("No validation results are available yet.")
    else:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "dataset": item.dataset_name,
                        "check": item.check_name,
                        "severity": item.severity,
                        "status": item.status,
                        "details": item.details,
                    }
                    for item in home.validation_results
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )

st.divider()
st.subheader("State routing")
state_snapshot = {
    "workspace_root": str(home.app_paths.workspace_root),
    "app_local_state_dir": str(home.app_paths.local_state_dir),
    "app_runs_root": str(home.app_paths.runs_root),
    "shared_registry_path": str(home.shared_paths.registry_path),
    "shared_lake_root": str(home.shared_paths.lake_root),
}
st.code(json.dumps(state_snapshot, indent=2), language="json")
