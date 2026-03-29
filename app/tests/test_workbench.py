from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import duckdb

from quantlab.registry import bootstrap_registry
from quantlab.storage import ensure_state_dirs
from quantlab.strategies.builtin import default_strategy_config


def _write_metrics(path: Path, total_return_pct: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        (
            "{\n"
            f'  "total_return_pct": {total_return_pct},\n'
            '  "max_drawdown_pct": 0.1,\n'
            '  "trade_count": 2,\n'
            '  "win_rate_pct": 0.5\n'
            "}\n"
        ),
        encoding="utf-8",
    )


def test_execute_backtest_run_persists_artifacts_under_app_state_root(tmp_path: Path) -> None:
    from app.ui.workbench import execute_backtest_run, seed_app_demo_data

    seed_app_demo_data(tmp_path)
    config = default_strategy_config(start_date="2022-01-03", end_date="2022-01-10")

    execution = execute_backtest_run(config, root=tmp_path)

    assert execution.success is True
    assert execution.manifest is not None
    assert execution.paths.local_state_dir == tmp_path / "app" / ".quantlab"
    assert execution.paths.runs_root == tmp_path / "app" / ".quantlab" / "runs"
    assert Path(execution.manifest.config_path).is_relative_to(tmp_path / "app")
    assert not (tmp_path / ".quantlab" / "runs" / execution.run_id).exists()


def test_load_recent_runs_catalog_combines_shared_and_app_state(tmp_path: Path) -> None:
    from app.ui.data_access import load_recent_runs_catalog
    from app.ui.workbench import build_app_paths, build_shared_paths

    shared_paths = build_shared_paths(tmp_path)
    app_paths = build_app_paths(tmp_path)
    ensure_state_dirs(shared_paths)
    ensure_state_dirs(app_paths)
    bootstrap_registry(shared_paths.registry_path)
    bootstrap_registry(app_paths.registry_path)

    shared_metrics = shared_paths.runs_root / "shared-run" / "metrics.json"
    app_metrics = app_paths.runs_root / "app-run" / "metrics.json"
    _write_metrics(shared_metrics, total_return_pct=0.12)
    _write_metrics(app_metrics, total_return_pct=0.08)

    with duckdb.connect(str(shared_paths.registry_path)) as connection:
        connection.execute(
            """
            insert into backtest_runs (
                run_id, strategy_name, start_date, end_date, execution_mode, status, created_at, completed_at, metrics_path, artifacts_dir
            ) values (?, ?, date '2022-01-03', date '2022-01-10', ?, ?, ?, ?, ?, ?)
            """,
            [
                "shared-run",
                "builtin_consecutive_down_rsi",
                "last_5m_vwap",
                "completed",
                datetime(2026, 3, 28, 8, 0, 0, tzinfo=UTC),
                datetime(2026, 3, 28, 8, 5, 0, tzinfo=UTC),
                str(shared_metrics),
                str(shared_paths.runs_root / "shared-run"),
            ],
        )
    with duckdb.connect(str(app_paths.registry_path)) as connection:
        connection.execute(
            """
            insert into backtest_runs (
                run_id, strategy_name, start_date, end_date, execution_mode, status, created_at, completed_at, metrics_path, artifacts_dir
            ) values (?, ?, date '2022-01-11', date '2022-01-14', ?, ?, ?, ?, ?, ?)
            """,
            [
                "app-run",
                "builtin_consecutive_down_rsi",
                "next_open_control",
                "completed",
                datetime(2026, 3, 28, 9, 0, 0, tzinfo=UTC),
                datetime(2026, 3, 28, 9, 5, 0, tzinfo=UTC),
                str(app_metrics),
                str(app_paths.runs_root / "app-run"),
            ],
        )

    summaries = load_recent_runs_catalog(limit=10, root=tmp_path)

    assert [item.run_id for item in summaries] == ["app-run", "shared-run"]
    assert summaries[0].total_return_pct == 0.08
    assert summaries[1].total_return_pct == 0.12


def test_detect_scan_runner_reports_available_hook() -> None:
    from app.ui.workbench import detect_scan_runner

    probe = detect_scan_runner()

    assert probe.available is True
    assert probe.runner_name in {"reports.run_parameter_scan", "reports.scans.run_parameter_scan"}
    assert "run_parameter_scan" in probe.message


def test_detect_provider_readiness_runner_reports_available_hook() -> None:
    from app.ui.workbench import detect_provider_readiness_runner

    probe = detect_provider_readiness_runner()

    assert probe.available is True
    assert probe.runner_name in {"reports.run_provider_readiness_check", "reports.artifacts.run_provider_readiness_check"}
    assert "run_provider_readiness_check" in probe.message


def test_load_experiment_library_entries_reads_app_local_structure(tmp_path: Path) -> None:
    from app.ui.data_access import load_experiment_library_entries

    library_root = tmp_path / "app" / "experiments" / "batch-alpha"
    library_root.mkdir(parents=True)
    (library_root / "notes.md").write_text("# Batch alpha\n", encoding="utf-8")

    entries = load_experiment_library_entries(root=tmp_path)

    assert entries
    assert entries[0].label == "experiments/batch-alpha"
    assert entries[0].kind == "directory"
