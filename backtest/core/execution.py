from __future__ import annotations

from datetime import date

import pandas as pd

from quantlab.schemas import ExecutionMode

from backtest.models import MarketDataBundle
from backtest.core.universe import next_trade_date


def target_execution_date(bundle: MarketDataBundle, trade_date: date, mode: ExecutionMode) -> date | None:
    if mode == ExecutionMode.NEXT_OPEN_CONTROL:
        return next_trade_date(bundle, trade_date)
    return trade_date


def minute_bars_for_fill(bundle: MarketDataBundle, symbol: str, trade_date: date) -> pd.DataFrame:
    return bundle.minute_lookup.get((symbol, trade_date), pd.DataFrame())


def raw_execution_price(
    bundle: MarketDataBundle,
    symbol: str,
    execution_date: date,
    mode: ExecutionMode,
) -> tuple[float | None, str | None]:
    bars = minute_bars_for_fill(bundle, symbol, execution_date)
    if bars.empty:
        return None, "missing minute bars"

    ordered = bars.sort_values("bar_start_ts").reset_index(drop=True)
    if mode == ExecutionMode.CLOSE_PROXY:
        return float(ordered.iloc[-1]["close"]), "close_proxy"
    if mode == ExecutionMode.LAST_5M_VWAP:
        tail = ordered.tail(5).copy()
        weighted_amount = pd.to_numeric(tail["amount"], errors="coerce").fillna(0.0).sum()
        weighted_volume = pd.to_numeric(tail["volume"], errors="coerce").fillna(0.0).sum()
        if weighted_amount > 0 and weighted_volume > 0:
            return float(weighted_amount / weighted_volume), "last_5m_vwap"
        return float(tail["close"].mean()), "last_5m_vwap_fallback"
    if mode == ExecutionMode.NEXT_OPEN_CONTROL:
        first_bar = ordered.iloc[0]
        open_price = first_bar["open"]
        if pd.isna(open_price):
            open_price = first_bar["close"]
        return float(open_price), "next_open_control"
    return None, "unsupported execution mode"


def apply_slippage(price: float, side: str, slippage_rate: float) -> float:
    if side == "buy":
        return price * (1 + slippage_rate)
    return price * (1 - slippage_rate)
