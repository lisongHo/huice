from __future__ import annotations

from datetime import datetime
from pathlib import Path

import duckdb

from quantlab.config import AppPaths
from quantlab.registry import bootstrap_registry
from quantlab.schemas import RunStatus
from quantlab.storage import ensure_state_dirs


def _paths(tmp_path: Path) -> AppPaths:
    paths = AppPaths.from_workspace(tmp_path)
    ensure_state_dirs(paths)
    bootstrap_registry(paths.registry_path)
    return paths


def test_home_page_loader_reads_recent_runs_and_latest_validation_summaries(tmp_path: Path) -> None:
    from app.ui.data_access import load_home_page_data

    paths = _paths(tmp_path)
    with duckdb.connect(str(paths.registry_path)) as connection:
        connection.execute(
            """
            insert into backtest_runs (
                run_id, strategy_name, start_date, end_date, execution_mode, status, created_at, metrics_path, artifacts_dir
            ) values
                ('run-001', 'builtin_consecutive_down_rsi', date '2022-01-03', date '2022-01-07', 'last_5m_vwap', 'completed', ?, '/tmp/run-001/metrics.json', '/tmp/run-001'),
                ('run-002', 'builtin_consecutive_down_rsi', date '2022-01-10', date '2022-01-14', 'next_open_control', 'created', ?, '/tmp/run-002/metrics.json', '/tmp/run-002')
            """,
            [datetime(2026, 3, 28, 9, 0, 0), datetime(2026, 3, 28, 10, 0, 0)],
        )
        connection.execute(
            """
            insert into validation_results (
                validation_run_id, dataset_name, check_name, severity, status, details
            ) values
                ('vr-001', 'minute_bars', 'duplicate_minute_key', 'error', 'failed', '000001 2022-01-03T14:57:00'),
                ('vr-002', 'minute_bars', 'illegal_ohlc', 'error', 'passed', 'ok')
            """
        )

    home_data = load_home_page_data(paths, limit=5)

    assert [run.run_id for run in home_data.recent_runs] == ["run-002", "run-001"]
    assert home_data.recent_runs[0].status == RunStatus.CREATED
    assert [item.check_name for item in home_data.validation_results] == [
        "duplicate_minute_key",
        "illegal_ohlc",
    ]


def test_run_submission_payload_requires_explicit_run_trigger(tmp_path: Path) -> None:
    from app.ui.data_access import build_run_submission
    from quantlab.strategies.builtin import default_strategy_config

    _paths(tmp_path)
    config = default_strategy_config(start_date="2022-01-03", end_date="2022-01-07")

    submission = build_run_submission(config, run_requested=False)

    assert submission.run_requested is False
    assert submission.config.run_id == config.run_id
    assert submission.config.execution.decision_time == "14:57"
    assert submission.summary["run_requested"] is False


def test_run_submission_payload_marks_requested_execution_explicitly(tmp_path: Path) -> None:
    from app.ui.data_access import build_run_submission
    from quantlab.strategies.builtin import default_strategy_config

    _paths(tmp_path)
    config = default_strategy_config(start_date="2022-01-03", end_date="2022-01-07")

    submission = build_run_submission(config, run_requested=True)

    assert submission.run_requested is True
    assert submission.summary["run_requested"] is True
    assert submission.payload["strategy_name"] == config.strategy_name


def test_latest_validation_summary_aggregates_status_and_severity_counts(tmp_path: Path) -> None:
    from app.ui.data_access import latest_data_health_note, load_home_page_data, load_latest_validation_summary

    paths = _paths(tmp_path)
    with duckdb.connect(str(paths.registry_path)) as connection:
        connection.execute(
            """
            insert into validation_results (
                validation_run_id, dataset_name, check_name, severity, status, details
            ) values
                ('vr-001', 'minute_bars', 'duplicate_minute_key', 'error', 'failed', 'duplicate minute key'),
                ('vr-002', 'minute_bars', 'invalid_session_time', 'error', 'failed', 'outside trading hours'),
                ('vr-003', 'minute_bars', 'missing_security_master', 'warning', 'skipped', 'security master unavailable'),
                ('vr-004', 'security_status_history', 'no_overlapping_effective_windows', 'error', 'pass', 'dated history is queryable')
            """
        )

    summary = load_latest_validation_summary(paths)
    home_data = load_home_page_data(paths, limit=5)

    assert summary is not None
    assert dict(zip(summary.status_counts["status"], summary.status_counts["count"])) == {
        "failed": 2,
        "pass": 1,
        "skipped": 1,
    }
    assert dict(zip(summary.severity_counts["severity"], summary.severity_counts["count"])) == {
        "error": 3,
        "warning": 1,
    }
    assert latest_data_health_note(paths) == "3 recent validation checks are not passing."
    assert home_data.data_health_note == "3 recent validation checks are not passing."
    assert [item.check_name for item in home_data.validation_results] == [
        "duplicate_minute_key",
        "invalid_session_time",
        "missing_security_master",
        "no_overlapping_effective_windows",
    ]
