from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import pandas as pd

from quantlab.config import AppPaths
from quantlab.schemas import MinuteBarRecord, SecurityStatusRecord
from quantlab.storage import dataset_root, ensure_state_dirs, minute_partition_path


def _paths(tmp_path: Path) -> AppPaths:
    paths = AppPaths.from_workspace(tmp_path)
    ensure_state_dirs(paths)
    return paths


def test_publish_minute_bars_normalizes_to_asia_shanghai_and_partitions_by_trade_date(
    tmp_path: Path,
) -> None:
    from data.ingest.publish import publish_minute_bars

    paths = _paths(tmp_path)
    bars = [
        MinuteBarRecord(
            symbol="000001",
            exchange="SZSE",
            trade_date=date(2022, 1, 4),
            bar_start_ts=datetime(2022, 1, 4, 14, 57, tzinfo=ZoneInfo("UTC")),
            bar_end_ts=datetime(2022, 1, 4, 14, 58, tzinfo=ZoneInfo("UTC")),
            open=10.0,
            high=10.2,
            low=9.9,
            close=10.1,
            volume=1_000,
            amount=10_100,
        )
    ]

    publish_minute_bars(paths, bars, provider_name="local_bundle")

    partition = minute_partition_path(paths, "2022-01-04")
    frame = pd.read_parquet(partition)

    assert partition.exists()
    assert frame.loc[0, "trade_date"].isoformat() == "2022-01-04"
    assert str(frame.loc[0, "bar_start_ts"].tzinfo) == "Asia/Shanghai"
    assert frame.loc[0, "bar_start_ts"].hour == 22
    assert list(frame.columns[:3]) == ["symbol", "exchange", "trade_date"]
    assert frame[["symbol", "bar_start_ts"]].duplicated().sum() == 0


def test_publish_security_status_history_is_queryable_by_effective_date(tmp_path: Path) -> None:
    from data.ingest.publish import publish_security_status_history

    paths = _paths(tmp_path)
    records = [
        SecurityStatusRecord(
            symbol="000001",
            effective_from=date(2022, 1, 1),
            effective_to=date(2022, 1, 9),
            name="Ping An Bank",
            is_st=False,
            status_reason="normal",
        ),
        SecurityStatusRecord(
            symbol="000001",
            effective_from=date(2022, 1, 10),
            effective_to=None,
            name="ST Ping An Bank",
            is_st=True,
            status_reason="special treatment",
        ),
    ]

    publish_security_status_history(paths, records, provider_name="local_bundle")

    history_root = dataset_root(paths, "security_status_history")
    query = """
        select symbol, name, is_st
        from read_parquet(?)
        where symbol = '000001'
          and effective_from <= date '2022-01-11'
          and (effective_to is null or effective_to >= date '2022-01-11')
    """

    with duckdb.connect() as connection:
        row = connection.execute(query, [str(history_root / "**/*.parquet")]).fetchone()

    assert row == ("000001", "ST Ping An Bank", True)
