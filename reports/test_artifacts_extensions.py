from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

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
from quantlab.storage import ensure_state_dirs, run_dir
from reports.artifacts import (
    ReplayDataHealth,
    ReplayDiagnosticPayload,
    ReplayTradeSlice,
    build_replay_diagnostic_payload,
    load_replay_diagnostic_payload,
    persist_backtest_result,
    persist_replay_diagnostic_payload,
)


def _paths(tmp_path: Path) -> AppPaths:
    paths = AppPaths.from_workspace(tmp_path)
    ensure_state_dirs(paths)
    bootstrap_registry(paths.registry_path)
    return paths


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
    return BacktestResult(
        run_id=run_id,
        config=config,
        metrics=BacktestMetrics(
            total_return_pct=4.0,
            annualized_return_pct=25.0,
            max_drawdown_pct=-1.5,
            win_rate_pct=1.0,
            turnover_ratio=0.2,
            trade_count=2,
        ),
        equity_curve=equity_curve,
        drawdown_curve=[
            DrawdownPoint(trade_date=date(2022, 1, 3), drawdown=0.0, peak_equity=1_000_000),
            DrawdownPoint(trade_date=date(2022, 1, 4), drawdown=0.0, peak_equity=1_020_000),
            DrawdownPoint(trade_date=date(2022, 1, 5), drawdown=-0.009804, peak_equity=1_020_000),
            DrawdownPoint(trade_date=date(2022, 1, 6), drawdown=0.0, peak_equity=1_040_000),
        ],
        trades=trades,
        annual_returns=[
            AnnualReturnPoint(year=2022, return_pct=0.04, max_drawdown_pct=-0.009804, trade_count=2)
        ],
    )


def test_build_replay_diagnostic_payload_creates_trade_slices_and_health_summary() -> None:
    result = _sample_result()

    payload = build_replay_diagnostic_payload(result)

    assert payload.run_id == result.run_id
    assert payload.data_health == ReplayDataHealth(
        equity_points=4,
        trade_count=2,
        closed_trade_count=1,
        open_lots=0,
        unique_symbols=1,
        first_trade_date=date(2022, 1, 4),
        last_trade_date=date(2022, 1, 6),
        warnings=[],
    )
    assert payload.trade_slices == [
        ReplayTradeSlice(
            symbol="000001",
            entry_trade_date=date(2022, 1, 4),
            exit_trade_date=date(2022, 1, 6),
            holding_days=2,
            shares=1000,
            entry_price=10.0,
            exit_price=10.4,
            gross_pnl=400.0,
            net_pnl=377.0,
            return_pct=0.037677,
            entry_notes="default T-1 signal entry",
            exit_notes="T+1 eligible exit",
        )
    ]


def test_persist_and_load_replay_diagnostic_payload_round_trip(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    result = _sample_result(run_id="replay-run-001")
    persist_backtest_result(paths, result)
    payload = ReplayDiagnosticPayload(
        run_id=result.run_id,
        generated_at=datetime(2026, 3, 28, 12, 0, tzinfo=UTC),
        data_health=ReplayDataHealth(
            equity_points=4,
            trade_count=2,
            closed_trade_count=1,
            open_lots=0,
            unique_symbols=1,
            first_trade_date=date(2022, 1, 4),
            last_trade_date=date(2022, 1, 6),
            warnings=[],
        ),
        trade_slices=[
            ReplayTradeSlice(
                symbol="000001",
                entry_trade_date=date(2022, 1, 4),
                exit_trade_date=date(2022, 1, 6),
                holding_days=2,
                shares=1000,
                entry_price=10.0,
                exit_price=10.4,
                gross_pnl=400.0,
                net_pnl=377.0,
                return_pct=0.037677,
                entry_notes="default T-1 signal entry",
                exit_notes="T+1 eligible exit",
            )
        ],
    )

    persisted = persist_replay_diagnostic_payload(paths, payload)
    loaded = load_replay_diagnostic_payload(paths, result.run_id)

    assert persisted.exists()
    assert persisted.parent == run_dir(paths, result.run_id)
    assert loaded == payload
