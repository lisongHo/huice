from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from quantlab.config import AppPaths
from quantlab.schemas import BacktestRunConfig

from backtest.models import MarketDataBundle

_DATE_COLUMNS = {
    "trade_date",
    "list_date",
    "delist_date",
    "effective_from",
    "effective_to",
    "prev_trade_date",
    "next_trade_date",
}
_DATETIME_COLUMNS = {"bar_start_ts", "bar_end_ts"}


def _empty_frame(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=columns)


def _dataset_path(lake_root: Path, candidates: list[str]) -> Path | None:
    for name in candidates:
        candidate = lake_root / name
        if candidate.exists():
            return candidate
    return None


def _read_dataset(lake_root: Path, names: list[str], columns: list[str]) -> pd.DataFrame:
    dataset_path = _dataset_path(lake_root, names)
    if dataset_path is None:
        return _empty_frame(columns)
    parquet_files = [dataset_path] if dataset_path.is_file() else sorted(dataset_path.rglob("*.parquet"))
    if not parquet_files:
        return _empty_frame(columns)
    frames = [pd.read_parquet(path) for path in parquet_files]
    frame = pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0]
    if frame.empty:
        return _empty_frame(columns)
    return frame


def _normalize_dates(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = frame.copy()
    for column in normalized.columns:
        if column in _DATE_COLUMNS:
            parsed = pd.to_datetime(normalized[column], errors="coerce")
            normalized[column] = parsed.dt.date.where(parsed.notna(), None)
        elif column in _DATETIME_COLUMNS:
            normalized[column] = pd.to_datetime(normalized[column], errors="coerce")
    return normalized


def _normalize_minute_bars(frame: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "symbol",
        "exchange",
        "trade_date",
        "bar_start_ts",
        "bar_end_ts",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "pre_close",
        "vwap",
        "is_synthetic_bar",
    ]
    if frame.empty:
        return _empty_frame(columns)
    normalized = _normalize_dates(frame)
    normalized = normalized.copy()
    for column in columns:
        if column not in normalized.columns:
            normalized[column] = None
    normalized["symbol"] = normalized["symbol"].astype(str)
    normalized["exchange"] = normalized["exchange"].fillna("").astype(str)
    normalized["trade_date"] = pd.to_datetime(normalized["trade_date"]).dt.date
    numeric_columns = ["open", "high", "low", "close", "volume", "amount", "pre_close", "vwap"]
    for column in numeric_columns:
        normalized[column] = pd.to_numeric(normalized[column], errors="coerce")
    normalized["is_synthetic_bar"] = normalized["is_synthetic_bar"].fillna(False).astype(bool)
    normalized = normalized.dropna(subset=["symbol", "trade_date", "bar_start_ts", "close"])
    normalized = normalized.sort_values(["symbol", "trade_date", "bar_start_ts"]).reset_index(drop=True)
    return normalized[columns]


def _normalize_security_master(frame: pd.DataFrame) -> pd.DataFrame:
    columns = ["symbol", "exchange", "list_date", "delist_date", "board", "name", "is_st"]
    if frame.empty:
        return _empty_frame(columns)
    normalized = _normalize_dates(frame)
    for column in columns:
        if column not in normalized.columns:
            normalized[column] = None
    normalized["symbol"] = normalized["symbol"].astype(str)
    normalized["exchange"] = normalized["exchange"].fillna("").astype(str)
    normalized["board"] = normalized["board"].fillna("").astype(str)
    normalized["name"] = normalized["name"].fillna("").astype(str)
    normalized["is_st"] = normalized["is_st"].fillna(False).astype(bool)
    normalized = normalized.drop_duplicates(subset=["symbol"], keep="last").reset_index(drop=True)
    return normalized[columns]


def _normalize_status_history(frame: pd.DataFrame) -> pd.DataFrame:
    columns = ["symbol", "effective_from", "effective_to", "name", "is_st", "status_reason"]
    if frame.empty:
        return _empty_frame(columns)
    normalized = _normalize_dates(frame)
    for column in columns:
        if column not in normalized.columns:
            normalized[column] = None
    normalized["symbol"] = normalized["symbol"].astype(str)
    normalized["name"] = normalized["name"].fillna("").astype(str)
    normalized["status_reason"] = normalized["status_reason"].fillna("").astype(str)
    normalized["is_st"] = normalized["is_st"].fillna(False).astype(bool)
    normalized = normalized.dropna(subset=["symbol", "effective_from"]).reset_index(drop=True)
    return normalized[columns]


def _normalize_suspensions(frame: pd.DataFrame) -> pd.DataFrame:
    columns = ["symbol", "trade_date", "is_suspended"]
    if frame.empty:
        return _empty_frame(columns)
    normalized = _normalize_dates(frame)
    for column in columns:
        if column not in normalized.columns:
            normalized[column] = None
    normalized["symbol"] = normalized["symbol"].astype(str)
    normalized["is_suspended"] = normalized["is_suspended"].fillna(True).astype(bool)
    normalized = normalized.dropna(subset=["symbol", "trade_date"]).reset_index(drop=True)
    return normalized[columns]


def _normalize_price_limits(frame: pd.DataFrame) -> pd.DataFrame:
    columns = ["symbol", "trade_date", "pre_close", "up_limit", "down_limit"]
    if frame.empty:
        return _empty_frame(columns)
    normalized = _normalize_dates(frame)
    for column in columns:
        if column not in normalized.columns:
            normalized[column] = None
    normalized["symbol"] = normalized["symbol"].astype(str)
    for column in ["pre_close", "up_limit", "down_limit"]:
        normalized[column] = pd.to_numeric(normalized[column], errors="coerce")
    normalized = normalized.dropna(subset=["symbol", "trade_date"]).reset_index(drop=True)
    return normalized[columns]


def _normalize_trading_calendar(frame: pd.DataFrame, minute_bars: pd.DataFrame) -> pd.DataFrame:
    columns = ["trade_date", "is_open", "prev_trade_date", "next_trade_date"]
    if frame.empty:
        if minute_bars.empty:
            return _empty_frame(columns)
        dates = sorted(minute_bars["trade_date"].dropna().unique().tolist())
        synthesized = []
        for index, trade_date in enumerate(dates):
            prev_date = dates[index - 1] if index > 0 else None
            next_date = dates[index + 1] if index + 1 < len(dates) else None
            synthesized.append(
                {
                    "trade_date": trade_date,
                    "is_open": True,
                    "prev_trade_date": prev_date,
                    "next_trade_date": next_date,
                }
            )
        return pd.DataFrame(synthesized, columns=columns)

    normalized = _normalize_dates(frame)
    for column in columns:
        if column not in normalized.columns:
            normalized[column] = None
    normalized["is_open"] = normalized["is_open"].fillna(True).astype(bool)
    normalized = normalized[normalized["is_open"]].dropna(subset=["trade_date"]).reset_index(drop=True)
    normalized = normalized.sort_values("trade_date").reset_index(drop=True)
    return normalized[columns]


def load_market_data(paths: AppPaths, config: BacktestRunConfig) -> MarketDataBundle:
    lake_root = paths.lake_root
    minute_bars = _normalize_minute_bars(
        _read_dataset(
            lake_root,
            ["minute_bars"],
            [
                "symbol",
                "exchange",
                "trade_date",
                "bar_start_ts",
                "bar_end_ts",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "amount",
                "pre_close",
                "vwap",
                "is_synthetic_bar",
            ],
        )
    )
    security_master = _normalize_security_master(
        _read_dataset(
            lake_root,
            ["security_master", "stock_basic"],
            ["symbol", "exchange", "list_date", "delist_date", "board", "name", "is_st"],
        )
    )
    status_history = _normalize_status_history(
        _read_dataset(
            lake_root,
            ["security_status_history", "namechange", "security_status"],
            ["symbol", "effective_from", "effective_to", "name", "is_st", "status_reason"],
        )
    )
    suspensions = _normalize_suspensions(
        _read_dataset(lake_root, ["suspensions", "suspension"], ["symbol", "trade_date", "is_suspended"])
    )
    price_limits = _normalize_price_limits(
        _read_dataset(
            lake_root,
            ["price_limits", "price_limit"],
            ["symbol", "trade_date", "pre_close", "up_limit", "down_limit"],
        )
    )
    trading_calendar = _normalize_trading_calendar(
        _read_dataset(
            lake_root,
            ["trade_calendar", "trade_cal"],
            ["trade_date", "is_open", "prev_trade_date", "next_trade_date"],
        ),
        minute_bars,
    )

    if not minute_bars.empty:
        minute_bars = minute_bars[
            (minute_bars["trade_date"] <= config.end_date)
            & (minute_bars["symbol"].str.startswith(config.universe.allowed_symbol_prefixes))
        ].reset_index(drop=True)

    if security_master.empty and not minute_bars.empty:
        inferred = (
            minute_bars.groupby("symbol", as_index=False)
            .agg(exchange=("exchange", "last"))
            .assign(delist_date=None, board="", name="", is_st=False)
        )
        inferred["list_date"] = None
        security_master = _normalize_security_master(inferred)

    trading_dates = trading_calendar["trade_date"].dropna().tolist()
    trading_date_index = {trade_date: index for index, trade_date in enumerate(trading_dates)}
    minute_lookup = {
        key: group.reset_index(drop=True)
        for key, group in minute_bars.groupby(["symbol", "trade_date"], sort=False)
    }
    price_limit_lookup = {
        (row.symbol, row.trade_date): (row.pre_close, row.up_limit, row.down_limit)
        for row in price_limits.itertuples(index=False)
    }
    suspension_lookup = {
        (row.symbol, row.trade_date)
        for row in suspensions.itertuples(index=False)
        if bool(row.is_suspended)
    }
    listing_lookup = {
        row.symbol: (row.list_date, row.delist_date)
        for row in security_master.itertuples(index=False)
    }
    symbol_meta = {
        row.symbol: {
            "exchange": row.exchange,
            "board": row.board,
            "name": row.name,
            "is_st": bool(row.is_st),
        }
        for row in security_master.itertuples(index=False)
    }

    return MarketDataBundle(
        lake_root=lake_root,
        minute_bars=minute_bars,
        security_master=security_master,
        security_status_history=status_history,
        suspensions=suspensions,
        price_limits=price_limits,
        trading_calendar=trading_calendar,
        minute_lookup=minute_lookup,
        price_limit_lookup=price_limit_lookup,
        suspension_lookup=suspension_lookup,
        listing_lookup=listing_lookup,
        symbol_meta=symbol_meta,
        trading_dates=trading_dates,
        trading_date_index=trading_date_index,
    )


def trading_dates_in_range(bundle: MarketDataBundle, start_date: date, end_date: date) -> list[date]:
    return [trade_date for trade_date in bundle.trading_dates if start_date <= trade_date <= end_date]


def previous_trade_date(bundle: MarketDataBundle, trade_date: date) -> date | None:
    index = bundle.trading_date_index.get(trade_date)
    if index is None or index == 0:
        return None
    return bundle.trading_dates[index - 1]


def next_trade_date(bundle: MarketDataBundle, trade_date: date) -> date | None:
    index = bundle.trading_date_index.get(trade_date)
    if index is None or index + 1 >= len(bundle.trading_dates):
        return None
    return bundle.trading_dates[index + 1]


def advance_trade_date(bundle: MarketDataBundle, trade_date: date, steps: int) -> date | None:
    index = bundle.trading_date_index.get(trade_date)
    if index is None:
        return None
    next_index = index + steps
    if next_index >= len(bundle.trading_dates):
        return None
    return bundle.trading_dates[next_index]


def is_st_on_date(bundle: MarketDataBundle, symbol: str, trade_date: date) -> bool:
    if not bundle.security_status_history.empty:
        effective_from = pd.to_datetime(
            bundle.security_status_history["effective_from"], errors="coerce"
        ).map(lambda value: value.date() if pd.notna(value) else None)
        effective_to = pd.to_datetime(
            bundle.security_status_history["effective_to"], errors="coerce"
        ).map(lambda value: value.date() if pd.notna(value) else None)
        rows = bundle.security_status_history[
            (bundle.security_status_history["symbol"] == symbol)
            & (effective_from <= trade_date)
            & (effective_to.isna() | (effective_to >= trade_date))
        ]
        if not rows.empty:
            return bool(rows.sort_values("effective_from").iloc[-1]["is_st"])
    meta = bundle.symbol_meta.get(symbol, {})
    return bool(meta.get("is_st", False))


def listing_trading_days(bundle: MarketDataBundle, symbol: str, trade_date: date) -> int | None:
    list_date, _ = bundle.listing_lookup.get(symbol, (None, None))
    if list_date is not None and pd.isna(list_date):
        list_date = None
    if list_date is None:
        return None
    if bundle.trading_dates and list_date < bundle.trading_dates[0]:
        return len([open_date for open_date in bundle.trading_dates if open_date <= trade_date]) + 1
    open_dates = [open_date for open_date in bundle.trading_dates if list_date <= open_date <= trade_date]
    return len(open_dates)


def is_listing_eligible(bundle: MarketDataBundle, symbol: str, trade_date: date, config: BacktestRunConfig) -> bool:
    list_date, delist_date = bundle.listing_lookup.get(symbol, (None, None))
    if list_date is not None and pd.isna(list_date):
        list_date = None
    if delist_date is not None and pd.isna(delist_date):
        delist_date = None
    if list_date is not None and not pd.isna(list_date) and trade_date < list_date:
        return False
    if delist_date is not None and not pd.isna(delist_date) and trade_date > delist_date:
        return False
    eligible_days = listing_trading_days(bundle, symbol, trade_date)
    if eligible_days is None:
        return True
    return eligible_days > config.rules.exclude_new_listed_days


def eligible_symbols_for_date(
    bundle: MarketDataBundle,
    config: BacktestRunConfig,
    trade_date: date,
) -> list[str]:
    symbols = sorted(
        {
            symbol
            for symbol, bar_date in bundle.minute_lookup.keys()
            if bar_date == trade_date and symbol.startswith(config.universe.allowed_symbol_prefixes)
        }
    )
    eligible: list[str] = []
    for symbol in symbols:
        if not is_listing_eligible(bundle, symbol, trade_date, config):
            continue
        if config.rules.exclude_st and is_st_on_date(bundle, symbol, trade_date):
            continue
        eligible.append(symbol)
    return eligible
