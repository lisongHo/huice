from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from data.ingest.publish import publish_minute_bars, publish_security_status_history
from quantlab.config import AppPaths
from quantlab.schemas import MinuteBarRecord, SecurityStatusRecord
from quantlab.storage import ensure_state_dirs


def _minute_bar(symbol: str, trade_date: date, minute: int, close: float, volume: float = 5_000) -> MinuteBarRecord:
    start_ts = datetime(
        trade_date.year,
        trade_date.month,
        trade_date.day,
        14,
        minute,
        tzinfo=ZoneInfo("Asia/Shanghai"),
    )
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


def seed_demo_data(paths: AppPaths | None = None) -> AppPaths:
    paths = paths or AppPaths.from_workspace()
    ensure_state_dirs(paths)

    symbol_series = {
        "000001": [10.20, 10.00, 9.80, 9.60, 9.90, 10.10, 10.35, 10.55],
        "600000": [12.10, 11.95, 11.70, 11.50, 11.35, 11.55, 11.80, 12.00],
        "300001": [20.50, 20.10, 19.80, 19.30, 19.10, 19.45, 19.90, 20.20],
    }
    trade_dates = [date(2022, 1, day) for day in range(3, 11)]
    minute_offsets = (55, 56, 57, 58, 59)

    bars: list[MinuteBarRecord] = []
    for symbol, closes in symbol_series.items():
        for trade_date, close in zip(trade_dates, closes, strict=True):
            for minute in minute_offsets:
                bars.append(_minute_bar(symbol, trade_date, minute, close))

    publish_minute_bars(paths, bars, provider_name="demo_seed")
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
            ),
            SecurityStatusRecord(
                symbol="600000",
                effective_from=date(2022, 1, 1),
                effective_to=None,
                name="Shanghai Pudong Development Bank",
                is_st=False,
                status_reason="normal",
            ),
            SecurityStatusRecord(
                symbol="300001",
                effective_from=date(2022, 1, 1),
                effective_to=None,
                name="Tech Growth Demo",
                is_st=False,
                status_reason="normal",
            ),
        ],
        provider_name="demo_seed",
    )
    return paths


def main() -> None:
    paths = seed_demo_data()
    print(f"Demo data seeded under {paths.lake_root}")
    print(f"Registry available at {paths.registry_path}")


if __name__ == "__main__":
    main()

