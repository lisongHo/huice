from __future__ import annotations

from datetime import date

import pandas as pd

from quantlab.schemas import BacktestRunConfig

from backtest.models import CandidateSignal, MarketDataBundle
from backtest.core.universe import previous_trade_date


def build_daily_bars(bundle: MarketDataBundle) -> pd.DataFrame:
    minute_bars = bundle.minute_bars
    if minute_bars.empty:
        return pd.DataFrame(
            columns=[
                "symbol",
                "trade_date",
                "exchange",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "amount",
                "pre_close",
                "vwap",
            ]
        )

    grouped = (
        minute_bars.groupby(["symbol", "trade_date"], as_index=False)
        .agg(
            exchange=("exchange", "last"),
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
            amount=("amount", "sum"),
            pre_close=("pre_close", "first"),
        )
        .sort_values(["symbol", "trade_date"])
        .reset_index(drop=True)
    )
    grouped["vwap"] = grouped["amount"] / grouped["volume"].where(grouped["volume"] > 0)
    grouped["vwap"] = grouped["vwap"].fillna(grouped["close"])
    return grouped


def _compute_rsi(series: pd.Series, window: int) -> pd.Series:
    delta = series.diff()
    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)
    avg_gain = gains.rolling(window=window, min_periods=window).mean()
    avg_loss = losses.rolling(window=window, min_periods=window).mean()
    rs = avg_gain / avg_loss.where(avg_loss > 0)
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.where(avg_loss > 0, 100.0)
    return rsi


def compute_daily_features(daily_bars: pd.DataFrame, config: BacktestRunConfig) -> pd.DataFrame:
    if daily_bars.empty:
        return daily_bars.copy()

    feature_frames: list[pd.DataFrame] = []
    for _, group in daily_bars.groupby("symbol", sort=False):
        symbol_bars = group.sort_values("trade_date").reset_index(drop=True).copy()
        symbol_bars["prev_close_daily"] = symbol_bars["close"].shift(1)
        symbol_bars["down_day"] = symbol_bars["close"] < symbol_bars["prev_close_daily"]
        streaks: list[int] = []
        streak = 0
        for down_day in symbol_bars["down_day"].fillna(False).tolist():
            streak = streak + 1 if down_day else 0
            streaks.append(streak)
        symbol_bars["consecutive_down_count"] = streaks
        symbol_bars["rsi"] = _compute_rsi(symbol_bars["close"], config.strategy_params.rsi_window)
        feature_frames.append(symbol_bars)

    return pd.concat(feature_frames, ignore_index=True).sort_values(["symbol", "trade_date"]).reset_index(drop=True)


def select_entry_candidates(
    bundle: MarketDataBundle,
    config: BacktestRunConfig,
    feature_frame: pd.DataFrame,
    decision_date: date,
    eligible_symbols: list[str],
    held_symbols: set[str],
) -> list[CandidateSignal]:
    feature_date = previous_trade_date(bundle, decision_date)
    if feature_date is None or feature_frame.empty:
        return []

    frame = feature_frame[
        (feature_frame["trade_date"] == feature_date)
        & (feature_frame["symbol"].isin(eligible_symbols))
        & feature_frame["rsi"].notna()
        & (feature_frame["rsi"] <= config.strategy_params.rsi_threshold)
        & (feature_frame["consecutive_down_count"] >= config.strategy_params.consecutive_down_days)
    ].copy()
    if not frame.empty and not config.portfolio.allow_same_symbol_overlap:
        frame = frame[~frame["symbol"].isin(held_symbols)]

    frame = frame.sort_values(
        ["rsi", "consecutive_down_count", "symbol"],
        ascending=[True, False, True],
    ).reset_index(drop=True)
    return [
        CandidateSignal(
            symbol=row.symbol,
            decision_date=decision_date,
            feature_date=feature_date,
            rsi=float(row.rsi),
            consecutive_down_count=int(row.consecutive_down_count),
        )
        for row in frame.itertuples(index=False)
    ]
