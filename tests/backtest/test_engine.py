from __future__ import annotations

from datetime import date, datetime
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from quantlab.config import AppPaths
from quantlab.schemas import BacktestRunConfig, ExecutionMode, MinuteBarRecord, SecurityStatusRecord
from quantlab.storage import ensure_state_dirs


def _paths(tmp_path: Path) -> AppPaths:
    paths = AppPaths.from_workspace(tmp_path)
    ensure_state_dirs(paths)
    return paths


def _minute_bar(
    symbol: str,
    trade_date: date,
    hour: int,
    minute: int,
    close: float,
    volume: float = 5_000,
) -> MinuteBarRecord:
    start_ts = datetime(trade_date.year, trade_date.month, trade_date.day, hour, minute, tzinfo=ZoneInfo("Asia/Shanghai"))
    return MinuteBarRecord(
        symbol=symbol,
        exchange="SZSE" if symbol.startswith(("00", "30")) else "SSE",
        trade_date=trade_date,
        bar_start_ts=start_ts,
        bar_end_ts=start_ts + timedelta(minutes=1),
        open=close,
        high=close,
        low=close,
        close=close,
        volume=volume,
        amount=close * volume,
    )


def test_default_control_strategy_uses_t_minus_one_daily_features_and_t_day_tail_close_execution(
    tmp_path: Path,
) -> None:
    from backtest.core.engine import run_backtest
    from data.ingest.publish import publish_minute_bars, publish_security_status_history

    paths = _paths(tmp_path)
    trade_dates = [date(2022, 1, day) for day in range(3, 8)]
    bars = []
    closes = {
        date(2022, 1, 3): 10.2,
        date(2022, 1, 4): 10.0,
        date(2022, 1, 5): 9.8,
        date(2022, 1, 6): 9.6,
        date(2022, 1, 7): 9.9,
    }
    for trade_date in trade_dates:
        for minute in (55, 56, 57, 58, 59):
            bars.append(_minute_bar("000001", trade_date, 14, minute, closes[trade_date]))

    publish_minute_bars(paths, bars, provider_name="local_bundle")
    publish_security_status_history(
        paths,
        [
            SecurityStatusRecord(
                symbol="000001",
                effective_from=date(2022, 1, 1),
                effective_to=None,
                name="Ping An Bank",
                is_st=False,
                status_reason="normal",
            )
        ],
        provider_name="local_bundle",
    )

    config = BacktestRunConfig.for_builtin_strategy(
        name="builtin_consecutive_down_rsi",
        start_date="2022-01-03",
        end_date="2022-01-07",
        execution_mode=ExecutionMode.LAST_5M_VWAP,
    )
    result = run_backtest(paths, config)

    assert result.config.execution.mode == ExecutionMode.LAST_5M_VWAP
    assert result.trades[0].trade_date == date(2022, 1, 6)
    assert result.trades[0].notes is not None
    assert "T-1" in result.trades[0].notes


def test_next_open_control_never_reads_completed_t_day_bars(tmp_path: Path) -> None:
    from backtest.core.engine import run_backtest
    from data.ingest.publish import publish_minute_bars, publish_security_status_history

    paths = _paths(tmp_path)
    for trade_date, close in [
        (date(2022, 1, 3), 10.3),
        (date(2022, 1, 4), 10.1),
        (date(2022, 1, 5), 9.9),
        (date(2022, 1, 6), 8.0),
        (date(2022, 1, 7), 10.5),
    ]:
        publish_minute_bars(
            paths,
            [_minute_bar("000001", trade_date, 14, 57, close), _minute_bar("000001", trade_date, 14, 58, close)],
            provider_name="local_bundle",
        )
    publish_security_status_history(
        paths,
        [
            SecurityStatusRecord(
                symbol="000001",
                effective_from=date(2022, 1, 1),
                effective_to=None,
                name="Ping An Bank",
                is_st=False,
                status_reason="normal",
            )
        ],
        provider_name="local_bundle",
    )

    config = BacktestRunConfig.for_builtin_strategy(
        name="builtin_consecutive_down_rsi",
        start_date="2022-01-03",
        end_date="2022-01-07",
        execution_mode=ExecutionMode.NEXT_OPEN_CONTROL,
    )
    result = run_backtest(paths, config)

    assert result.config.execution.mode == ExecutionMode.NEXT_OPEN_CONTROL
    assert all(trade.trade_date >= date(2022, 1, 7) for trade in result.trades if trade.side == "buy")
