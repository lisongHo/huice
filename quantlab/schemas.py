from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ExecutionMode(str, Enum):
    CLOSE_PROXY = "close_proxy"
    LAST_5M_VWAP = "last_5m_vwap"
    NEXT_OPEN_CONTROL = "next_open_control"


class AdjustmentMode(str, Enum):
    RAW = "raw"
    FORWARD = "forward"
    BACKWARD = "backward"


class RunStatus(str, Enum):
    CREATED = "created"
    COMPLETED = "completed"
    FAILED = "failed"


class StrategyTimingMode(str, Enum):
    DEFAULT_CONTROL = "default_control"
    EXPERIMENTAL_SAME_DAY_PROXY = "experimental_same_day_proxy"


class PortfolioConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    initial_cash: float = 1_000_000
    max_positions: int = 10
    board_lot_size: int = 100
    allow_same_symbol_overlap: bool = False
    equal_weight: bool = True


class FeeConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    commission_rate: float = 0.0003
    min_commission: float = 5.0
    transfer_fee_rate: float = 0.00001
    stamp_duty_sell_rate: float = 0.001
    slippage_rate: float = 0.0005


class RuleConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    enforce_t_plus_one: bool = True
    enforce_price_limits: bool = True
    enforce_suspension: bool = True
    exclude_st: bool = True
    exclude_new_listed_days: int = 5


class ExecutionConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    mode: ExecutionMode = ExecutionMode.LAST_5M_VWAP
    timing_mode: StrategyTimingMode = StrategyTimingMode.DEFAULT_CONTROL
    decision_time: str = "14:57"
    last_5m_participation_cap: float = 0.2


class StrategyParams(BaseModel):
    model_config = ConfigDict(frozen=True)

    consecutive_down_days: int = 2
    rsi_window: int = 2
    rsi_threshold: float = 30.0
    hold_days: int = 3


class UniverseConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    allowed_symbol_prefixes: tuple[str, ...] = ("00", "30", "60")


class BacktestRunConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str = Field(default_factory=lambda: uuid4().hex)
    strategy_name: str
    start_date: date
    end_date: date
    timezone: str = "Asia/Shanghai"
    adjustment_mode: AdjustmentMode = AdjustmentMode.RAW
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    portfolio: PortfolioConfig = Field(default_factory=PortfolioConfig)
    fees: FeeConfig = Field(default_factory=FeeConfig)
    rules: RuleConfig = Field(default_factory=RuleConfig)
    universe: UniverseConfig = Field(default_factory=UniverseConfig)
    strategy_params: StrategyParams = Field(default_factory=StrategyParams)

    @field_validator("end_date")
    @classmethod
    def validate_range(cls, value: date, info: Any) -> date:
        start_date = info.data.get("start_date")
        if start_date and value < start_date:
            raise ValueError("end_date must be on or after start_date")
        return value

    @classmethod
    def for_builtin_strategy(
        cls,
        name: str,
        start_date: str | date,
        end_date: str | date,
        execution_mode: ExecutionMode = ExecutionMode.LAST_5M_VWAP,
    ) -> "BacktestRunConfig":
        return cls(
            strategy_name=name,
            start_date=start_date,
            end_date=end_date,
            execution=ExecutionConfig(mode=execution_mode),
        )


class MinuteBarRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    exchange: str
    trade_date: date
    bar_start_ts: datetime
    bar_end_ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float
    pre_close: float | None = None
    vwap: float | None = None
    is_synthetic_bar: bool = False


class SecurityStatusRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    effective_from: date
    effective_to: date | None = None
    name: str
    is_st: bool
    status_reason: str


class RunArtifactManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    status: RunStatus = RunStatus.CREATED
    config_path: str
    metrics_path: str
    equity_curve_path: str
    drawdown_curve_path: str
    trades_path: str
    annual_returns_path: str | None = None


class TradeRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    trade_date: date
    side: str
    shares: int
    price: float
    amount: float
    fees: float
    execution_mode: ExecutionMode
    notes: str | None = None


class EquityPoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    trade_date: date
    equity: float
    cash: float
    market_value: float


class DrawdownPoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    trade_date: date
    drawdown: float
    peak_equity: float


class AnnualReturnPoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    year: int
    return_pct: float
    max_drawdown_pct: float
    trade_count: int


class BacktestMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_return_pct: float
    annualized_return_pct: float
    max_drawdown_pct: float
    win_rate_pct: float
    turnover_ratio: float
    trade_count: int


class BacktestResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    config: BacktestRunConfig
    metrics: BacktestMetrics
    equity_curve: list[EquityPoint]
    drawdown_curve: list[DrawdownPoint]
    trades: list[TradeRecord]
    annual_returns: list[AnnualReturnPoint]
