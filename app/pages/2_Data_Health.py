from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.ui.data_access import load_data_health_snapshot  # noqa: E402


st.set_page_config(page_title="Data Health", layout="wide")
snapshot = load_data_health_snapshot()

st.title("Data Health")
st.caption("Read-only view of persisted validation and dataset registry artifacts.")

metric_col1, metric_col2, metric_col3 = st.columns(3)
with metric_col1:
    st.metric("Validation samples", len(snapshot.validation_results))
with metric_col2:
    st.metric("Datasets tracked", len(snapshot.file_manifest))
with metric_col3:
    st.metric("Providers tracked", len(snapshot.provider_capabilities))

st.info(snapshot.note)

summary_col1, summary_col2 = st.columns(2)
with summary_col1:
    st.subheader("Status counts")
    if snapshot.validation_summary is None:
        st.info("No validation summary is available yet.")
    else:
        st.dataframe(snapshot.validation_summary.status_counts, use_container_width=True, hide_index=True)
with summary_col2:
    st.subheader("Severity counts")
    if snapshot.validation_summary is None:
        st.info("No validation summary is available yet.")
    else:
        st.dataframe(snapshot.validation_summary.severity_counts, use_container_width=True, hide_index=True)

detail_col1, detail_col2 = st.columns((1.2, 1))
with detail_col1:
    st.subheader("Recent validation checks")
    if not snapshot.validation_results:
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
                    for item in snapshot.validation_results
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )
with detail_col2:
    st.subheader("Dataset files")
    if not snapshot.file_manifest:
        st.info("No file-manifest rows are available yet.")
    else:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "dataset": item.dataset_name,
                        "files": item.file_count,
                        "rows": item.row_count,
                    }
                    for item in snapshot.file_manifest
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )

st.subheader("Provider capabilities")
if not snapshot.provider_capabilities:
    st.info("No provider-capability rows are available yet.")
else:
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "provider": item.provider_name,
                    "minute_bars": item.supports_minute_bars,
                    "security_status_history": item.supports_security_status_history,
                    "price_limits": item.supports_price_limits,
                    "suspensions": item.supports_suspensions,
                }
                for item in snapshot.provider_capabilities
            ]
        ),
        use_container_width=True,
        hide_index=True,
    )
