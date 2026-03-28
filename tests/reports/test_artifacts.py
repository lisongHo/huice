from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import duckdb

from quantlab.config import AppPaths
from quantlab.registry import bootstrap_registry
from quantlab.schemas import (
    AnnualReturnPoint,
    BacktestMetrics,
    BacktestResult,
    BacktestRunConfig,
    DrawdownPoint,
    EquityPoint,
    RunStatus,
    TradeRecord,
)
from quantlab.storage import ARTIFACT_FILE_NAMES, ensure_state_dirs, run_dir
from reports.artifacts import load_backtest_result, persist_backtest_result
from reports.metrics import (
    calculate_annual_returns,
    calculate_backtest_metrics,
    calculate_drawdown_curve,
)
from reports.scans import (
    ScanBatchResult,
    ScanParameterSet,
    ScanRunSummary,
    load_scan_batch_result,
    persist_scan_batch_result,
)


def _sample_result(run_id: str = "run-report-001") -> BacktestResult:
    config = BacktestRunConfig.for_builtin_strategy(
        name="builtin_consecutive_down_rsi",
        start_date="2022-01-03",
        end_date="2022-01-07",
    ).model_copy(update={"run_id": run_id})
    equity_curve = [
        EquityPoint(trade_date=date(2022, 1, 3), equity=1_000_000, cash=1_000_000, market_value=0),
        EquityPoint(trade_date=date(2022, 1, 4), equity=1_020_000, cash=600_000, market_value=420_000),
        EquityPoint(trade_date=date(2022, 1, 5), equity=1_010_000, cash=610_000, market_value=400_000),
        EquityPoint(trade_date=date(2022, 1, 6), equity=1_040_000, cash=1_040_000, market_value=0),
    ]
    trades = [
        TradeRecord(
            symbol="000001",
            trade_date=date(2022, 1, 4),
            side="buy",
            shares=1000,
            price=10.0,
            amount=10_000.0,
            fees=6.0,
            execution_mode=config.execution.mode,
            notes="default T-1 signal entry",
        ),
        TradeRecord(
            symbol="000001",
            trade_date=date(2022, 1, 6),
            side="sell",
            shares=1000,
            price=10.4,
            amount=10_400.0,
            fees=17.0,
            execution_mode=config.execution.mode,
            notes="T+1 eligible exit",
        ),
    ]
    drawdown_curve = calculate_drawdown_curve(equity_curve)
    annual_returns = calculate_annual_returns(equity_curve, trades)
    metrics = calculate_backtest_metrics(equity_curve, trades)
    return BacktestResult(
        run_id=run_id,
        config=config,
        metrics=metrics,
        equity_curve=equity_curve,
        drawdown_curve=drawdown_curve,
        trades=trades,
        annual_returns=annual_returns,
    )


def _paths(tmp_path: Path) -> AppPaths:
    paths = AppPaths.from_workspace(tmp_path)
    ensure_state_dirs(paths)
    bootstrap_registry(paths.registry_path)
    return paths


def test_metric_helpers_produce_expected_summary_and_curves() -> None:
    equity_curve = [
        EquityPoint(trade_date=date(2022, 1, 3), equity=1_000_000, cash=1_000_000, market_value=0),
        EquityPoint(trade_date=date(2022, 1, 4), equity=1_050_000, cash=500_000, market_value=550_000),
        EquityPoint(trade_date=date(2022, 1, 5), equity=1_020_000, cash=520_000, market_value=500_000),
        EquityPoint(trade_date=date(2022, 1, 6), equity=1_100_000, cash=1_100_000, market_value=0),
    ]
    trades = [
        TradeRecord(
            symbol="600000",
            trade_date=date(2022, 1, 4),
            side="buy",
            shares=1000,
            price=11.0,
            amount=11_000.0,
            fees=6.0,
            execution_mode="last_5m_vwap",
        ),
        TradeRecord(
            symbol="600000",
            trade_date=date(2022, 1, 6),
            side="sell",
            shares=1000,
            price=11.8,
            amount=11_800.0,
            fees=18.0,
            execution_mode="last_5m_vwap",
        ),
    ]

    drawdown_curve = calculate_drawdown_curve(equity_curve)
    annual_returns = calculate_annual_returns(equity_curve, trades)
    metrics = calculate_backtest_metrics(equity_curve, trades)

    assert [point.drawdown for point in drawdown_curve] == [0.0, 0.0, -0.028571, 0.0]
    assert annual_returns == [
        AnnualReturnPoint(year=2022, return_pct=0.1, max_drawdown_pct=-0.028571, trade_count=2)
    ]
    assert metrics.total_return_pct == 0.1
    assert metrics.max_drawdown_pct == -0.028571
    assert metrics.trade_count == 2
    assert metrics.win_rate_pct == 1.0


def test_persist_and_load_backtest_result_round_trip(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    result = _sample_result()

    manifest = persist_backtest_result(paths, result)
    artifact_dir = run_dir(paths, result.run_id)

    assert manifest.run_id == result.run_id
    assert manifest.status == RunStatus.COMPLETED
    assert artifact_dir.exists()
    assert sorted(path.name for path in artifact_dir.iterdir()) == sorted(ARTIFACT_FILE_NAMES.values())

    config_payload = json.loads((artifact_dir / "config.json").read_text())
    metrics_payload = json.loads((artifact_dir / "metrics.json").read_text())
    manifest_payload = json.loads((artifact_dir / "manifest.json").read_text())

    assert config_payload["run_id"] == result.run_id
    assert config_payload["execution"]["mode"] == "last_5m_vwap"
    assert metrics_payload["trade_count"] == 2
    assert manifest_payload["annual_returns_path"].endswith("annual_returns.parquet")

    loaded = load_backtest_result(paths, result.run_id)

    assert loaded == result

    with duckdb.connect(str(paths.registry_path)) as connection:
        row = connection.execute(
            """
            select run_id, strategy_name, execution_mode, status, metrics_path, artifacts_dir
            from backtest_runs
            where run_id = ?
            """,
            [result.run_id],
        ).fetchone()

    assert row == (
        result.run_id,
        result.config.strategy_name,
        result.config.execution.mode.value,
        RunStatus.COMPLETED.value,
        str(artifact_dir / ARTIFACT_FILE_NAMES["metrics"]),
        str(artifact_dir),
    )


def test_persist_backtest_result_is_immutable_for_existing_run_id(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    result = _sample_result(run_id="immutable-run-id")

    persist_backtest_result(paths, result)

    try:
        persist_backtest_result(paths, result)
    except FileExistsError as exc:
        assert result.run_id in str(exc)
    else:
        raise AssertionError("persist_backtest_result must reject overwriting existing artifacts")


def test_scan_batch_round_trip_and_registry_row(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    result = _sample_result(run_id="scan-candidate-run")
    persist_backtest_result(paths, result)

    batch = ScanBatchResult(
        scan_batch_id="scan-batch-001",
        strategy_name=result.config.strategy_name,
        created_at="2026-03-28T10:00:00+08:00",
        parameter_sets=[
            ScanParameterSet(name="rsi_threshold", value=25.0),
            ScanParameterSet(name="hold_days", value=3),
            ScanParameterSet(name="label", value="baseline"),
            ScanParameterSet(name="use_signal_filter", value=True),
        ],
        runs=[
            ScanRunSummary(
                run_id=result.run_id,
                params={"rsi_threshold": 25.0, "hold_days": 3, "label": "baseline", "use_signal_filter": True},
                total_return_pct=result.metrics.total_return_pct,
                max_drawdown_pct=result.metrics.max_drawdown_pct,
                trade_count=result.metrics.trade_count,
                annualized_return_pct=result.metrics.annualized_return_pct,
            )
        ],
    )

    persisted_path = persist_scan_batch_result(paths, batch)
    loaded = load_scan_batch_result(paths, batch.scan_batch_id)

    assert persisted_path.exists()
    assert loaded == batch

    with duckdb.connect(str(paths.registry_path)) as connection:
        row = connection.execute(
            """
            select scan_batch_id, strategy_name, result_path
            from scan_batches
            where scan_batch_id = ?
            """,
            [batch.scan_batch_id],
        ).fetchone()

    assert row == (batch.scan_batch_id, batch.strategy_name, str(persisted_path))


def test_load_run_artifacts_tolerates_partial_replay_artifacts(tmp_path: Path) -> None:
    from app.ui.data_access import load_run_artifacts

    paths = _paths(tmp_path)
    result = _sample_result(run_id="partial-replay-run")
    artifact_dir = run_dir(paths, result.run_id)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "config.json").write_text(json.dumps(result.config.model_dump(mode="json"), indent=2))
    (artifact_dir / "metrics.json").write_text(json.dumps(result.metrics.model_dump(mode="json"), indent=2))

    loaded = load_run_artifacts(result.run_id, paths=paths)

    assert loaded.run_id == result.run_id
    assert loaded.manifest is None
    assert loaded.config == result.config
    assert loaded.metrics == result.metrics.model_dump(mode="json")
    assert loaded.equity_curve.empty
    assert loaded.drawdown_curve.empty
    assert loaded.trades.empty
    assert loaded.annual_returns.empty
