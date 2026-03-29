from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

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


def test_latest_validation_summary_treats_pass_and_passed_as_the_same_status(tmp_path: Path) -> None:
    from app.ui.data_access import latest_data_health_note, load_latest_validation_summary

    paths = _paths(tmp_path)
    with duckdb.connect(str(paths.registry_path)) as connection:
        connection.execute(
            """
            insert into validation_results (
                validation_run_id, dataset_name, check_name, severity, status, details
            ) values
                ('vr-101', 'minute_bars', 'duplicate_minute_key', 'error', 'failed', 'duplicate minute key'),
                ('vr-102', 'minute_bars', 'illegal_ohlc', 'error', 'pass', 'ok'),
                ('vr-103', 'security_status_history', 'no_overlapping_effective_windows', 'warning', 'passed', 'dated history is queryable')
            """
        )

    summary = load_latest_validation_summary(paths)

    assert summary is not None
    assert dict(zip(summary.status_counts["status"], summary.status_counts["count"])) == {
        "pass": 2,
        "failed": 1,
    }
    assert latest_data_health_note(paths) == "1 recent validation checks are not passing."


def test_home_page_loader_reports_preflight_when_real_data_is_missing(tmp_path: Path) -> None:
    from app.ui.data_access import load_home_page_data

    paths = _paths(tmp_path)

    home_data = load_home_page_data(paths, limit=5)

    assert home_data.readiness_summary.status == "warning"
    assert "No real provider data" in home_data.readiness_summary.headline
    assert any("seed demo data" in step.lower() for step in home_data.readiness_summary.next_steps)


def test_home_page_loader_reports_missing_provider_permissions(tmp_path: Path) -> None:
    from app.ui.data_access import load_home_page_data

    paths = _paths(tmp_path)
    with duckdb.connect(str(paths.registry_path)) as connection:
        connection.execute(
            """
            insert into provider_capabilities (
                provider_name, supports_minute_bars, supports_security_status_history, supports_price_limits, supports_suspensions
            ) values
                ('tushare_pro', true, false, false, false)
            """
        )

    home_data = load_home_page_data(paths, limit=5)

    assert home_data.readiness_summary.status == "warning"
    assert "security-status history" in home_data.readiness_summary.headline.lower()


def test_latest_saved_readiness_summary_infers_permission_gap_from_raw_tushare_payload(tmp_path: Path) -> None:
    from app.ui.data_access import load_latest_saved_readiness_summary

    paths = _paths(tmp_path)
    readiness_dir = paths.local_state_dir / "readiness"
    readiness_dir.mkdir(parents=True, exist_ok=True)
    (readiness_dir / "latest.json").write_text(
        """
        {
          "config": {
            "config_path": "/tmp/provider.toml",
            "api_url": "http://api.tushare.pro",
            "token_visible": true,
            "reference_date": "2026-03-29"
          },
          "endpoint_probes": [
            {"api_name": "trade_cal", "status": "ok", "row_count": 1},
            {"api_name": "stock_basic", "status": "ok", "row_count": 1},
            {
              "api_name": "stk_mins",
              "status": "error",
              "selected_symbol": "000001",
              "error_type": "TushareConfigurationError",
              "error_message": "Tushare permission error for stk_mins: 权限不足. Minute-data permission is missing for this token."
            }
          ]
        }
        """.strip(),
        encoding="utf-8",
    )

    summary = load_latest_saved_readiness_summary(paths=paths)

    assert summary is not None
    assert summary.status == "warning"
    assert "minute" in summary.headline.lower()
    assert any("permission" in step.lower() for step in summary.next_steps)


def test_latest_readiness_artifact_prefers_most_recent_saved_file(tmp_path: Path) -> None:
    from app.ui.data_access import load_latest_readiness_artifact

    paths = AppPaths.from_workspace(tmp_path)
    readiness_dir = paths.local_state_dir / "readiness"
    readiness_dir.mkdir(parents=True, exist_ok=True)

    older_path = readiness_dir / "2026-03-27.json"
    newer_path = readiness_dir / "2026-03-28.json"
    older_path.write_text(
        """
        {
          "status": "warning",
          "headline": "Older saved readiness",
          "body": "This should not be selected.",
          "next_steps": ["Ignore me"]
        }
        """.strip(),
        encoding="utf-8",
    )
    newer_path.write_text(
        """
        {
          "status": "success",
          "headline": "Latest saved readiness",
          "body": "This should be selected.",
          "next_steps": ["Use the latest artifact"]
        }
        """.strip(),
        encoding="utf-8",
    )

    older_mtime = datetime(2026, 3, 27, 9, 0, 0).timestamp()
    newer_mtime = datetime(2026, 3, 28, 9, 0, 0).timestamp()
    os.utime(older_path, (older_mtime, older_mtime))
    os.utime(newer_path, (newer_mtime, newer_mtime))

    artifact = load_latest_readiness_artifact(paths)

    assert artifact is not None
    assert artifact.path.endswith("2026-03-28.json")
    assert artifact.summary.headline == "Latest saved readiness"
    assert artifact.summary.status == "success"
    assert artifact.summary.next_steps == ["Use the latest artifact"]


def test_home_page_loader_prefers_saved_readiness_artifact(tmp_path: Path, monkeypatch) -> None:
    from app.ui import data_access

    paths = _paths(tmp_path)
    fake_artifact = SimpleNamespace(
        summary=SimpleNamespace(
            status="success",
            headline="Saved readiness artifact",
            body="Loaded from shared state.",
            next_steps=["Open the provider readiness page."],
        )
    )

    monkeypatch.setattr(data_access, "load_latest_readiness_artifact", lambda *args, **kwargs: fake_artifact)
    monkeypatch.setattr(
        data_access,
        "build_home_readiness_summary",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("generic readiness summary should not be used")),
    )
    monkeypatch.setattr(data_access, "load_latest_validation_summary", lambda paths=None: None)
    monkeypatch.setattr(data_access, "load_recent_runs", lambda limit=10, paths=None, source_label="app": [])
    monkeypatch.setattr(data_access, "load_recent_runs_catalog", lambda limit=10, root=None: [])
    monkeypatch.setattr(data_access, "load_provider_capabilities", lambda paths=None: [])
    monkeypatch.setattr(data_access, "load_file_manifest_summary", lambda paths=None: [])
    monkeypatch.setattr(data_access, "default_template_summary", lambda: SimpleNamespace())
    monkeypatch.setattr(data_access, "load_latest_saved_template", lambda paths=None, root=None: None)
    monkeypatch.setattr(data_access, "latest_data_health_note", lambda paths=None: "No validation results are available yet.")
    monkeypatch.setattr(data_access, "load_scan_batches", lambda limit=10, root=None: [])
    monkeypatch.setattr(data_access, "load_experiment_library_entries", lambda root=None: [])
    monkeypatch.setattr(data_access, "load_data_health_snapshot", lambda root=None: SimpleNamespace(
        validation_results=[],
        validation_summary=None,
        note="No validation results are available yet.",
        file_manifest=[],
        provider_capabilities=[],
    ))

    home_data = data_access.load_home_page_data(paths=paths, limit=5)

    assert home_data.readiness_summary.headline == "Saved readiness artifact"
    assert home_data.readiness_summary.status == "success"
