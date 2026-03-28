from __future__ import annotations

from datetime import date

from quantlab.schemas import BacktestRunConfig, ExecutionMode

from backtest.models import (
    Fill,
    HoldingState,
    MarketContext,
    MarketDataBundle,
    OrderRequest,
    Position,
    SimulatedOrderFill,
)
from backtest.core.execution import apply_slippage, raw_execution_price
from backtest.core.universe import is_st_on_date


def _price_limit_pct(symbol: str, is_st: bool) -> float:
    if is_st:
        return 0.05
    if symbol.startswith("30"):
        return 0.20
    return 0.10


def _price_limits(bundle: MarketDataBundle, symbol: str, trade_date: date) -> tuple[float | None, float | None]:
    pre_close, up_limit, down_limit = bundle.price_limit_lookup.get((symbol, trade_date), (None, None, None))
    if up_limit is not None and down_limit is not None:
        return float(up_limit), float(down_limit)

    minute_bars = bundle.minute_lookup.get((symbol, trade_date))
    if minute_bars is not None and not minute_bars.empty:
        candidate_pre_close = minute_bars.iloc[0].get("pre_close")
        if candidate_pre_close is not None:
            pre_close = float(candidate_pre_close)

    if pre_close is None:
        return None, None

    limit_pct = _price_limit_pct(symbol, is_st_on_date(bundle, symbol, trade_date))
    return round(pre_close * (1 + limit_pct), 2), round(pre_close * (1 - limit_pct), 2)


def is_suspended(bundle: MarketDataBundle, symbol: str, trade_date: date) -> bool:
    if (symbol, trade_date) in bundle.suspension_lookup:
        return True
    minute_bars = bundle.minute_lookup.get((symbol, trade_date))
    if minute_bars is None or minute_bars.empty:
        return True
    return False


def trade_fees(
    config: BacktestRunConfig,
    symbol: str,
    exchange: str | None,
    side: str,
    gross_amount: float,
) -> float:
    commission = max(config.fees.min_commission, gross_amount * config.fees.commission_rate)
    exchange_text = (exchange or "").upper()
    applies_transfer_fee = exchange_text in {"SH", "SSE"} or symbol.startswith("60")
    transfer_fee = gross_amount * config.fees.transfer_fee_rate if applies_transfer_fee else 0.0
    stamp_duty = gross_amount * config.fees.stamp_duty_sell_rate if side == "sell" else 0.0
    return float(commission + transfer_fee + stamp_duty)


def build_buy_fill(
    bundle: MarketDataBundle,
    config: BacktestRunConfig,
    symbol: str,
    execution_date: date,
    budget: float,
) -> Fill | None:
    raw_price, note = raw_execution_price(bundle, symbol, execution_date, config.execution.mode)
    if raw_price is None:
        return None
    if config.rules.enforce_suspension and is_suspended(bundle, symbol, execution_date):
        return None

    price = apply_slippage(raw_price, "buy", config.fees.slippage_rate)
    up_limit, _ = _price_limits(bundle, symbol, execution_date)
    if config.rules.enforce_price_limits and up_limit is not None and price >= up_limit:
        return None

    board_lot_size = config.portfolio.board_lot_size
    shares = int(budget // price // board_lot_size) * board_lot_size
    exchange = str(bundle.symbol_meta.get(symbol, {}).get("exchange", ""))
    while shares > 0:
        amount = float(shares * price)
        fees = trade_fees(config, symbol, exchange, "buy", amount)
        if amount + fees <= budget:
            break
        shares -= board_lot_size
    if shares <= 0:
        return None
    amount = float(shares * price)
    fees = trade_fees(config, symbol, exchange, "buy", amount)

    return Fill(
        symbol=symbol,
        side="buy",
        trade_date=execution_date,
        shares=shares,
        price=float(price),
        amount=amount,
        fees=fees,
        execution_mode=config.execution.mode.value,
        notes=note,
    )


def build_sell_fill(
    bundle: MarketDataBundle,
    config: BacktestRunConfig,
    position: Position,
    execution_date: date,
) -> Fill | None:
    raw_price, note = raw_execution_price(bundle, position.symbol, execution_date, config.execution.mode)
    if raw_price is None:
        return None
    if config.rules.enforce_suspension and is_suspended(bundle, position.symbol, execution_date):
        return None

    price = apply_slippage(raw_price, "sell", config.fees.slippage_rate)
    _, down_limit = _price_limits(bundle, position.symbol, execution_date)
    if config.rules.enforce_price_limits and down_limit is not None and price <= down_limit:
        return None
    if config.rules.enforce_t_plus_one and execution_date <= position.entry_date:
        return None

    amount = float(position.shares * price)
    fees = trade_fees(config, position.symbol, position.exchange, "sell", amount)
    return Fill(
        symbol=position.symbol,
        side="sell",
        trade_date=execution_date,
        shares=position.shares,
        price=float(price),
        amount=amount,
        fees=fees,
        execution_mode=config.execution.mode.value,
        notes=note,
    )


def simulate_order(
    order: OrderRequest,
    holding: HoldingState | None,
    context: MarketContext,
    config: BacktestRunConfig,
) -> SimulatedOrderFill:
    if context.is_suspended and config.rules.enforce_suspension:
        return SimulatedOrderFill(status="rejected_suspension")

    if order.side == "buy":
        if holding is not None and not config.portfolio.allow_same_symbol_overlap:
            return SimulatedOrderFill(status="rejected_existing_position")
        if context.is_st and config.rules.exclude_st:
            return SimulatedOrderFill(status="rejected_st")
        if context.at_up_limit and config.rules.enforce_price_limits:
            return SimulatedOrderFill(status="rejected_price_limit")
        budget = min(float(order.target_cash), float(context.available_cash))
        shares = int(budget // context.execution_price // context.lot_size) * context.lot_size
        if shares <= 0:
            return SimulatedOrderFill(status="rejected_insufficient_cash")
        amount = float(shares * context.execution_price)
        fees = trade_fees(config, order.symbol, None, "buy", amount)
        return SimulatedOrderFill(
            status="filled",
            shares=shares,
            price=float(context.execution_price),
            amount=amount,
            fees=fees,
        )

    if holding is None or holding.shares <= 0:
        return SimulatedOrderFill(status="rejected_no_position")
    if config.rules.enforce_t_plus_one and order.trade_date <= holding.entry_trade_date:
        return SimulatedOrderFill(status="rejected_t_plus_one")
    if context.at_down_limit and config.rules.enforce_price_limits:
        return SimulatedOrderFill(status="rejected_price_limit")
    amount = float(holding.shares * context.execution_price)
    fees = trade_fees(config, order.symbol, None, "sell", amount)
    return SimulatedOrderFill(
        status="filled",
        shares=int(holding.shares),
        price=float(context.execution_price),
        amount=amount,
        fees=fees,
    )
