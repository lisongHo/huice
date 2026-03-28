from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import pandas as pd

from data.providers.base import ProviderCapabilities
from data.providers.local_bundle import LocalBundleProvider
from quantlab.config import AppPaths
from quantlab.storage import ensure_state_dirs


def _paths(tmp_path: Path) -> AppPaths:
    paths = AppPaths.from_workspace(tmp_path)
    ensure_state_dirs(paths)
    return paths


def _session_minutes(trade_date: date) -> list[datetime]:
    morning = [datetime(trade_date.year, trade_date.month, trade_date.day, 9, 30, tzinfo=ZoneInfo("Asia/Shanghai")) + timedelta(minutes=offset) for offset in range(120)]
    afternoon = [datetime(trade_date.year, trade_date.month, trade_date.day, 13, 0, tzinfo=ZoneInfo("Asia/Shanghai")) + timedelta(minutes=offset) for offset in range(120)]
    return morning + afternoon


def _minute_bars_frame(symbol: str = "000001.SZ", trade_date: date = date(2022, 1, 3)) -> pd.DataFrame:
    rows = []
    for index, start_ts in enumerate(_session_minutes(trade_date), start=1):
        rows.append(
            {
                "symbol": symbol,
                "exchange": "SZSE",
                "trade_date": trade_date,
                "bar_start_ts": start_ts,
                "bar_end_ts": start_ts + timedelta(minutes=1),
                "open": 10.0 + index / 10_000,
                "high": 10.0 + index / 10_000,
                "low": 10.0 + index / 10_000,
                "close": 10.0 + index / 10_000,
                "volume": 1_000,
                "amount": 10_000.0,
            }
        )
    return pd.DataFrame(rows)


def _status_history_frame(symbol: str = "000001", trade_date: date = date(2022, 1, 3)) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": symbol,
                "effective_from": trade_date.replace(day=1),
                "effective_to": None,
                "name": "Ping An Bank",
                "is_st": False,
                "status_reason": "normal",
            }
        ]
    )


@dataclass
class _RecordingProvider:
    minute_bars: pd.DataFrame
    status_history: pd.DataFrame
    calls: list[str] = field(default_factory=list)
    name: str = "mock_real_provider"

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_minute_bars=True,
            supports_security_status_history=True,
            supports_price_limits=False,
            supports_suspensions=False,
        )

    def get_minute_bars(self, start_date=None, end_date=None, symbols=None) -> pd.DataFrame:
        self.calls.append("minute_bars")
        return self.minute_bars.copy()

    def get_security_master(self) -> pd.DataFrame:
        raise AssertionError("security_master should not be fetched for this contract")

    def get_security_status_history(self, start_date=None, end_date=None, symbols=None) -> pd.DataFrame:
        self.calls.append("security_status_history")
        return self.status_history.copy()

    def get_trade_calendar(self, start_date=None, end_date=None) -> pd.DataFrame:
        raise AssertionError("trade_calendar should not be fetched for this contract")

    def get_adjustment_factors(self, start_date=None, end_date=None, symbols=None) -> pd.DataFrame:
        raise AssertionError("adjustment_factors should not be fetched for this contract")

    def get_suspensions(self, start_date=None, end_date=None, symbols=None) -> pd.DataFrame:
        raise AssertionError("suspensions should not be fetched for this contract")

    def get_price_limits(self, start_date=None, end_date=None, symbols=None) -> pd.DataFrame:
        raise AssertionError("price_limits should not be fetched for this contract")


def test_publish_from_provider_records_capabilities_and_respects_selected_datasets(tmp_path: Path) -> None:
    from data.ingest.publish import publish_from_provider

    paths = _paths(tmp_path)
    provider = _RecordingProvider(
        minute_bars=_minute_bars_frame(),
        status_history=_status_history_frame(),
    )

    result = publish_from_provider(
        provider=provider,
        paths=paths,
        dataset_names=["minute_bars", "security_status_history"],
        start_date=date(2022, 1, 3),
        end_date=date(2022, 1, 3),
        symbols=["000001"],
        notes="contract-test",
    )

    assert provider.calls == ["minute_bars", "security_status_history"]
    assert result.datasets == {"minute_bars": 240, "security_status_history": 1}
    assert result.files
    assert all(item.status != "failed" for item in result.validation_results)

    with duckdb.connect(str(paths.registry_path)) as connection:
        capability_row = connection.execute(
            """
            select provider_name, supports_minute_bars, supports_security_status_history,
                   supports_price_limits, supports_suspensions
            from provider_capabilities
            where provider_name = ?
            """,
            [provider.name],
        ).fetchone()
        run_row = connection.execute(
            """
            select provider_name, status, notes
            from ingestion_runs
            where provider_name = ?
            order by started_at desc
            limit 1
            """,
            [provider.name],
        ).fetchone()

    assert capability_row == (provider.name, True, True, False, False)
    assert run_row == (provider.name, "completed", "contract-test")


def test_local_bundle_provider_missing_bundle_is_safe_without_credentials(tmp_path: Path) -> None:
    provider = LocalBundleProvider(bundle_root=tmp_path / "missing-bundle")

    assert provider.capabilities() == ProviderCapabilities()
    assert provider.get_minute_bars().empty
    assert provider.get_security_master().empty
    assert provider.get_security_status_history().empty
