from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol, Sequence

import pandas as pd

SUPPORTED_DATASETS: tuple[str, ...] = (
    "minute_bars",
    "security_master",
    "security_status_history",
    "trade_calendar",
    "adjustment_factors",
    "suspensions",
    "price_limits",
)


@dataclass(frozen=True)
class ProviderCapabilities:
    supports_minute_bars: bool = True
    supports_security_status_history: bool = True
    supports_price_limits: bool = True
    supports_suspensions: bool = True


class DataProvider(Protocol):
    name: str

    def capabilities(self) -> ProviderCapabilities:
        ...

    def get_minute_bars(
        self,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
        symbols: Sequence[str] | None = None,
    ) -> pd.DataFrame:
        ...

    def get_security_master(self) -> pd.DataFrame:
        ...

    def get_security_status_history(
        self,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
        symbols: Sequence[str] | None = None,
    ) -> pd.DataFrame:
        ...

    def get_trade_calendar(
        self,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> pd.DataFrame:
        ...

    def get_adjustment_factors(
        self,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
        symbols: Sequence[str] | None = None,
    ) -> pd.DataFrame:
        ...

    def get_suspensions(
        self,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
        symbols: Sequence[str] | None = None,
    ) -> pd.DataFrame:
        ...

    def get_price_limits(
        self,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
        symbols: Sequence[str] | None = None,
    ) -> pd.DataFrame:
        ...
