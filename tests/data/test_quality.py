from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from quantlab.schemas import MinuteBarRecord


def _bar(
    *,
    symbol: str = "000001",
    trade_date: date = date(2022, 1, 4),
    bar_start_ts: datetime = datetime(2022, 1, 4, 14, 57, tzinfo=ZoneInfo("Asia/Shanghai")),
    open: float = 10.0,
    high: float = 10.2,
    low: float = 9.9,
    close: float = 10.1,
    volume: float = 1_000,
    amount: float = 10_100,
) -> MinuteBarRecord:
    return MinuteBarRecord(
        symbol=symbol,
        exchange="SZSE",
        trade_date=trade_date,
        bar_start_ts=bar_start_ts,
        bar_end_ts=bar_start_ts.replace(minute=bar_start_ts.minute + 1),
        open=open,
        high=high,
        low=low,
        close=close,
        volume=volume,
        amount=amount,
    )


def test_quality_checks_flag_duplicate_minute_keys() -> None:
    from data.quality.checks import validate_minute_bars

    duplicated = [
        _bar(),
        _bar(),
    ]

    issues = validate_minute_bars(duplicated)

    assert any(issue.check_name == "duplicate_minute_key" for issue in issues)


def test_quality_checks_flag_illegal_ohlc_relationships() -> None:
    from data.quality.checks import validate_minute_bars

    issues = validate_minute_bars(
        [
            _bar(high=9.8, low=9.9, close=9.7),
        ]
    )

    assert any(issue.check_name == "illegal_ohlc" for issue in issues)


def test_quality_checks_flag_negative_volume_or_amount() -> None:
    from data.quality.checks import validate_minute_bars

    issues = validate_minute_bars(
        [
            _bar(volume=-1, amount=-10),
        ]
    )

    assert any(issue.check_name == "negative_volume_or_amount" for issue in issues)
