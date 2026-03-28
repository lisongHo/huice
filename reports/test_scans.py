from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from quantlab.config import AppPaths
from quantlab.registry import bootstrap_registry
from quantlab.schemas import (
    AnnualReturnPoint,
    BacktestMetrics,
    BacktestResult,
    BacktestRunConfig,
    DrawdownPoint,
    EquityPoint,
    TradeRecord,
)
from quantlab.storage import ensure_state_dirs
from reports.scans import run_parameter_scan


def _paths(tmp_path: Path) -> AppPaths:
    paths = AppPaths.from_workspace(tmp_path)
    ensure_state_dirs(paths)
    bootstrap_registry(paths.registry_path)
    return paths


def _result_for_config(config: BacktestRunConfig) -> BacktestResult:
    total_return_pct = float(config.strategy_params.rsi_threshold)
    max_drawdown_pct = -float(config.strategy_params.hold_days)
    metrics = BacktestMetrics(
        total_return_pct=total_return_pct,
        annualized_return_pct=total_return_pct / 2.0,
        max_drawdown_pct=max_drawdown_pct,
        win_rate_pct=0.5,
        turnover_ratio=0.25,
        trade_count=config.strategy_params.hold_days,
    )
    return BacktestResult(
        run_id=config.run_id,
        config=config,
        metrics=metrics,
        equity_curve=[
            EquityPoint(
                trade_date=date(2022, 1, 3),
                equity=1_000_000 + total_return_pct,
                cash=800_000,
                market_value=200_000,
            )
        ],
        drawdown_curve=[
            DrawdownPoint(
                trade_date=date(2022, 1, 3),
                drawdown=max_drawdown_pct / 100.0,
                peak_equity=1_000_000 + total_return_pct,
            )
        ],
        trades=[
            TradeRecord(
                symbol="000001",
                trade_date=date(2022, 1, 3),
                side="buy",
                shares=100 * config.strategy_params.hold_days,
                price=10.0,
                amount=1_000.0,
                fees=5.0,
                execution_mode=config.execution.mode,
                notes="scan-test",
            )
        ],
        annual_returns=[
            AnnualReturnPoint(
                year=2022,
                return_pct=total_return_pct,
                max_drawdown_pct=max_drawdown_pct,
                trade_count=config.strategy_params.hold_days,
            )
        ],
    )


def test_run_parameter_scan_reuses_prepared_market_data_and_shapes_ranked_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_config = BacktestRunConfig.for_builtin_strategy(
        name="builtin_consecutive_down_rsi",
        start_date="2022-01-03",
        end_date="2022-01-07",
    )
    paths = _paths(tmp_path)
    prepared_data = object()
    prepare_calls: list[str] = []
    seen_run_ids: list[str] = []

    def fake_prepare(call_paths: AppPaths, config: BacktestRunConfig) -> object:
        assert call_paths == paths
        prepare_calls.append(config.run_id)
        return prepared_data

    def fake_run(prepared: object, config: BacktestRunConfig) -> BacktestResult:
        assert prepared is prepared_data
        seen_run_ids.append(config.run_id)
        return _result_for_config(config)

    monkeypatch.setattr("reports.scans.prepare_backtest_data", fake_prepare)
    monkeypatch.setattr("reports.scans.run_backtest_with_prepared_data", fake_run)

    batch = run_parameter_scan(
        paths=paths,
        base_config=base_config,
        parameter_grid={
            "rsi_threshold": [20.0, 35.0],
            "hold_days": [2, 4],
        },
        scan_batch_id="scan-batch-001",
    )

    assert prepare_calls == [base_config.run_id]
    assert len(seen_run_ids) == 4
    assert len(set(seen_run_ids)) == 4
    assert [run.rank for run in batch.runs] == [1, 2, 3, 4]
    assert batch.best_run_id == batch.runs[0].run_id
    assert batch.aggregate is not None
    assert batch.aggregate.completed_runs == 4
    assert batch.aggregate.best_total_return_pct == 35.0
    assert batch.aggregate.worst_max_drawdown_pct == -4.0
    assert batch.parameter_names == ["hold_days", "rsi_threshold"]
    assert batch.runs[0].params == {"rsi_threshold": 35.0, "hold_days": 2}
    assert batch.runs[0].score == 35.0

