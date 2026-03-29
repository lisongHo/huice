from __future__ import annotations

from pathlib import Path

from data.ingest.sync import (
    GapIssue,
    GapScanResult,
    SyncExecutionResult,
    SyncRunSummary,
    coerce_sync_run_request,
    execute_sync_request,
    sync_run_request_to_dict,
)
from data.providers.tushare_provider import TushareConfigurationError
from quantlab.config import AppPaths
from quantlab.schemas import SyncRunRequest, SyncWorkflow


def test_coerce_sync_run_request_normalizes_enums_and_payloads() -> None:
    request = coerce_sync_run_request(
        {
            "workflow": "weekly-maintenance",
            "start_date": "2026-03-01",
            "end_date": "2026-03-05",
            "config_path": "/tmp/provider.toml",
            "symbols": ("000001", "600000"),
            "dry_run": False,
        }
    )

    assert isinstance(request, SyncRunRequest)
    assert request.workflow is SyncWorkflow.WEEKLY_MAINTENANCE
    assert request.symbols == ["000001", "600000"]
    assert sync_run_request_to_dict(request) == {
        "sync_run_id": request.sync_run_id,
        "workflow": "weekly-maintenance",
        "start_date": "2026-03-01",
        "end_date": "2026-03-05",
        "config_path": "/tmp/provider.toml",
        "symbols": ["000001", "600000"],
        "dry_run": False,
    }


def test_execute_sync_request_formats_success_summary(monkeypatch) -> None:
    paths = AppPaths.from_workspace(Path("/tmp/quantlab-sync-tests"))
    request = {
        "workflow": "weekly-maintenance",
        "start_date": "2026-03-01",
        "end_date": "2026-03-05",
        "config_path": None,
        "symbols": ["000001"],
        "dry_run": False,
    }
    summary = SyncRunSummary(
        workflow="weekly-maintenance",
        reference_sync={"security_master": 1, "trade_calendar": 2},
        minute_windows=(
            {
                "start_date": "2026-03-01",
                "end_date": "2026-03-03",
                "trade_dates": ("2026-03-02", "2026-03-03"),
                "row_counts": {"minute_bars": 480},
                "written_files": 2,
            },
        ),
        gap_scan=GapScanResult(
            expected_trade_dates=("2026-03-02", "2026-03-03"),
            expected_symbol_count=1,
            issue_count=1,
            affected_trade_dates=("2026-03-03",),
            issues=(
                GapIssue(trade_date="2026-03-03", symbol="000001", actual_bars=239),
            ),
        ),
    )

    monkeypatch.setattr(
        "data.ingest.sync.run_refresh",
        lambda **kwargs: summary,
    )

    result = execute_sync_request(paths=paths, request_payload=request)

    assert isinstance(result, SyncExecutionResult)
    assert result.error is None
    assert result.request.workflow is SyncWorkflow.WEEKLY_MAINTENANCE
    assert result.request_payload["workflow"] == "weekly-maintenance"
    assert result.summary_payload["workflow"] == "weekly-maintenance"
    assert result.summary_payload["status"] == "completed"
    assert result.summary_payload["reference_sync"] == {"security_master": 1, "trade_calendar": 2}
    assert result.summary_payload["minute_windows"][0]["row_counts"] == {"minute_bars": 480}
    assert result.summary_payload["gap_scan"]["issue_count"] == 1
    assert result.summary_payload["gap_scan"]["issues"][0]["symbol"] == "000001"


def test_execute_sync_request_formats_failure_summary(monkeypatch) -> None:
    paths = AppPaths.from_workspace(Path("/tmp/quantlab-sync-tests"))
    request = SyncRunRequest(
        workflow=SyncWorkflow.BACKFILL,
        start_date="2026-03-01",
        end_date="2026-03-05",
        dry_run=False,
    )

    def fake_run_backfill(**kwargs):
        raise TushareConfigurationError(
            "Tushare permission error for stk_mins: 权限不足. Minute-data permission is missing for this token."
        )

    monkeypatch.setattr("data.ingest.sync.run_backfill", fake_run_backfill)

    result = execute_sync_request(paths=paths, request_payload=request)

    assert isinstance(result, SyncExecutionResult)
    assert isinstance(result.error, TushareConfigurationError)
    assert result.summary_payload["workflow"] == "backfill"
    assert result.summary_payload["status"] == "failed"
    assert result.summary_payload["reference_sync"] == {}
    assert result.summary_payload["minute_windows"] == ()
    assert result.summary_payload["error_type"] == "TushareConfigurationError"
    assert "minute-data permission is missing" in result.summary_payload["error"].lower()
