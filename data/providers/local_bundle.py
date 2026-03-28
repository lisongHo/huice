from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from data.providers.base import ProviderCapabilities


def canonicalize_symbol(value: Any) -> str:
    raw = str(value).strip().upper()
    if not raw:
        raise ValueError("symbol cannot be empty")

    for separator in (".", "_", "-"):
        if separator in raw:
            head, _, tail = raw.partition(separator)
            if head.isdigit() and len(head) == 6:
                return head
            if tail.isdigit() and len(tail) == 6:
                return tail

    digits = "".join(character for character in raw if character.isdigit())
    if len(digits) == 6:
        return digits

    raise ValueError(f"unable to canonicalize symbol: {value!r}")


def infer_exchange(symbol: str) -> str:
    if symbol.startswith(("00", "30")):
        return "SZSE"
    if symbol.startswith("60"):
        return "SSE"
    return "UNKNOWN"


@dataclass(frozen=True)
class LocalBundleProvider:
    name: str = "local_bundle"
    bundle_root: Path | None = None
    bundle: Mapping[str, pd.DataFrame] | None = None

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities()

    def get_minute_bars(
        self,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
        symbols: Sequence[str] | None = None,
    ) -> pd.DataFrame:
        frame = self._load_dataset("minute_bars")
        return self._filter_by_date_and_symbol(frame, "trade_date", start_date, end_date, symbols)

    def get_security_master(self) -> pd.DataFrame:
        return self._load_dataset("security_master")

    def get_security_status_history(
        self,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
        symbols: Sequence[str] | None = None,
    ) -> pd.DataFrame:
        frame = self._load_dataset("security_status_history")
        return self._filter_by_date_and_symbol(frame, "effective_from", start_date, end_date, symbols)

    def get_trade_calendar(
        self,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> pd.DataFrame:
        frame = self._load_dataset("trade_calendar")
        return self._filter_by_date(frame, "trade_date", start_date, end_date)

    def get_adjustment_factors(
        self,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
        symbols: Sequence[str] | None = None,
    ) -> pd.DataFrame:
        frame = self._load_dataset("adjustment_factors")
        return self._filter_by_date_and_symbol(frame, "ex_date", start_date, end_date, symbols)

    def get_suspensions(
        self,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
        symbols: Sequence[str] | None = None,
    ) -> pd.DataFrame:
        frame = self._load_dataset("suspensions")
        return self._filter_by_date_and_symbol(frame, "trade_date", start_date, end_date, symbols)

    def get_price_limits(
        self,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
        symbols: Sequence[str] | None = None,
    ) -> pd.DataFrame:
        frame = self._load_dataset("price_limits")
        return self._filter_by_date_and_symbol(frame, "trade_date", start_date, end_date, symbols)

    def _load_dataset(self, dataset_name: str) -> pd.DataFrame:
        if self.bundle and dataset_name in self.bundle:
            return self.bundle[dataset_name].copy()

        if self.bundle_root is None:
            return pd.DataFrame()

        path = self._resolve_bundle_path(dataset_name)
        if path is None:
            return pd.DataFrame()

        if path.suffix == ".parquet":
            return pd.read_parquet(path)
        if path.suffix == ".csv":
            return pd.read_csv(path)
        if path.suffix == ".json":
            return pd.read_json(path)

        raise ValueError(f"unsupported bundle file format: {path}")

    def _resolve_bundle_path(self, dataset_name: str) -> Path | None:
        assert self.bundle_root is not None
        for extension in (".parquet", ".csv", ".json"):
            candidate = self.bundle_root / f"{dataset_name}{extension}"
            if candidate.exists():
                return candidate
        return None

    @staticmethod
    def _filter_by_date(
        frame: pd.DataFrame,
        date_column: str,
        start_date: date | str | None,
        end_date: date | str | None,
    ) -> pd.DataFrame:
        if frame.empty:
            return frame.copy()

        result = frame.copy()
        effective_date_column = date_column
        if effective_date_column not in result.columns:
            if "bar_start_ts" in result.columns:
                effective_date_column = "bar_start_ts"
            else:
                return result

        result[effective_date_column] = pd.to_datetime(result[effective_date_column])
        if effective_date_column == "bar_start_ts":
            comparison_series = result[effective_date_column].dt.date
        else:
            comparison_series = result[effective_date_column].dt.date

        if start_date is not None:
            start = pd.Timestamp(start_date).date()
            result = result[comparison_series >= start]
        if end_date is not None:
            end = pd.Timestamp(end_date).date()
            result = result[comparison_series <= end]

        return result.reset_index(drop=True)

    @classmethod
    def _filter_by_date_and_symbol(
        cls,
        frame: pd.DataFrame,
        date_column: str,
        start_date: date | str | None,
        end_date: date | str | None,
        symbols: Sequence[str] | None,
    ) -> pd.DataFrame:
        result = cls._filter_by_date(frame, date_column, start_date, end_date)
        if result.empty or not symbols or "symbol" not in result.columns:
            return result

        canonical_symbols = {canonicalize_symbol(symbol) for symbol in symbols}
        normalized_symbols = result["symbol"].map(canonicalize_symbol)
        return result[normalized_symbols.isin(canonical_symbols)].reset_index(drop=True)
