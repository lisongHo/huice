from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd


@dataclass(frozen=True)
class CandidateSignal:
    symbol: str
    decision_date: date
    feature_date: date
    rsi: float
    consecutive_down_count: int


@dataclass(frozen=True)
class PendingOrder:
    symbol: str
    side: str
    decision_date: date
    execution_date: date
    budget: float | None = None
    shares: int | None = None


@dataclass
class Position:
    symbol: str
    shares: int
    entry_date: date
    entry_price: float
    entry_fees: float
    scheduled_exit_date: date | None
    board: str | None = None
    exchange: str | None = None
    last_mark_price: float | None = None

    @property
    def cost_basis(self) -> float:
        return (self.entry_price * self.shares) + self.entry_fees


@dataclass(frozen=True)
class Fill:
    symbol: str
    side: str
    trade_date: date
    shares: int
    price: float
    amount: float
    fees: float
    execution_mode: str
    notes: str | None = None


@dataclass(frozen=True)
class OrderRequest:
    symbol: str
    trade_date: date
    side: str
    target_cash: float


@dataclass(frozen=True)
class HoldingState:
    symbol: str
    shares: int
    entry_trade_date: date


@dataclass(frozen=True)
class MarketContext:
    is_suspended: bool
    is_st: bool
    at_up_limit: bool
    at_down_limit: bool
    lot_size: int
    execution_price: float
    available_cash: float


@dataclass(frozen=True)
class SimulatedOrderFill:
    status: str
    shares: int = 0
    price: float | None = None
    amount: float = 0.0
    fees: float = 0.0


@dataclass
class MarketDataBundle:
    lake_root: Path
    minute_bars: pd.DataFrame
    security_master: pd.DataFrame
    security_status_history: pd.DataFrame
    suspensions: pd.DataFrame
    price_limits: pd.DataFrame
    trading_calendar: pd.DataFrame
    minute_lookup: dict[tuple[str, date], pd.DataFrame] = field(default_factory=dict)
    price_limit_lookup: dict[tuple[str, date], tuple[float | None, float | None, float | None]] = field(
        default_factory=dict
    )
    suspension_lookup: set[tuple[str, date]] = field(default_factory=set)
    listing_lookup: dict[str, tuple[date | None, date | None]] = field(default_factory=dict)
    symbol_meta: dict[str, dict[str, object]] = field(default_factory=dict)
    trading_dates: list[date] = field(default_factory=list)
    trading_date_index: dict[date, int] = field(default_factory=dict)


@dataclass(frozen=True)
class PreparedBacktestData:
    bundle: MarketDataBundle
    trade_dates: tuple[date, ...]
    daily_bars: pd.DataFrame


@dataclass
class LedgerState:
    cash: float
    positions: dict[str, Position] = field(default_factory=dict)
    trades: list = field(default_factory=list)
    equity_curve: list = field(default_factory=list)
    realized_pnls: list[float] = field(default_factory=list)
    total_turnover: float = 0.0
