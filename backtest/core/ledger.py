from __future__ import annotations

from datetime import date

from quantlab.schemas import EquityPoint, TradeRecord

from backtest.models import Fill, LedgerState, Position


def initialize_ledger(initial_cash: float) -> LedgerState:
    return LedgerState(cash=float(initial_cash))


def apply_buy(
    state: LedgerState,
    fill: Fill,
    scheduled_exit_date: date | None,
    board: str | None = None,
    exchange: str | None = None,
) -> None:
    state.cash -= fill.amount + fill.fees
    state.positions[fill.symbol] = Position(
        symbol=fill.symbol,
        shares=fill.shares,
        entry_date=fill.trade_date,
        entry_price=fill.price,
        entry_fees=fill.fees,
        scheduled_exit_date=scheduled_exit_date,
        board=board,
        exchange=exchange,
        last_mark_price=fill.price,
    )
    state.trades.append(
        TradeRecord(
            symbol=fill.symbol,
            trade_date=fill.trade_date,
            side=fill.side,
            shares=fill.shares,
            price=fill.price,
            amount=fill.amount,
            fees=fill.fees,
            execution_mode=fill.execution_mode,
            notes=fill.notes,
        )
    )
    state.total_turnover += fill.amount


def apply_sell(state: LedgerState, fill: Fill) -> None:
    position = state.positions.pop(fill.symbol, None)
    if position is None:
        return
    state.cash += fill.amount - fill.fees
    realized_pnl = (fill.amount - fill.fees) - position.cost_basis
    state.realized_pnls.append(realized_pnl)
    state.trades.append(
        TradeRecord(
            symbol=fill.symbol,
            trade_date=fill.trade_date,
            side=fill.side,
            shares=fill.shares,
            price=fill.price,
            amount=fill.amount,
            fees=fill.fees,
            execution_mode=fill.execution_mode,
            notes=fill.notes,
        )
    )
    state.total_turnover += fill.amount


def record_equity(
    state: LedgerState,
    trade_date: date,
    price_by_symbol: dict[str, float],
) -> None:
    market_value = 0.0
    for position in state.positions.values():
        mark_price = price_by_symbol.get(position.symbol, position.last_mark_price or position.entry_price)
        position.last_mark_price = mark_price
        market_value += position.shares * mark_price

    state.equity_curve.append(
        EquityPoint(
            trade_date=trade_date,
            equity=state.cash + market_value,
            cash=state.cash,
            market_value=market_value,
        )
    )
