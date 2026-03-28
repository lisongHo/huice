from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Sequence
from datetime import date

from quantlab.schemas import (
    AnnualReturnPoint,
    BacktestMetrics,
    DrawdownPoint,
    EquityPoint,
    TradeRecord,
)


def _round_metric(value: float) -> float:
    return round(float(value), 6)


def _sort_equity_curve(equity_curve: Sequence[EquityPoint]) -> list[EquityPoint]:
    return sorted(equity_curve, key=lambda point: point.trade_date)


def calculate_drawdown_curve(equity_curve: Sequence[EquityPoint]) -> list[DrawdownPoint]:
    sorted_curve = _sort_equity_curve(equity_curve)
    peak_equity = 0.0
    drawdown_curve: list[DrawdownPoint] = []
    for point in sorted_curve:
        peak_equity = max(peak_equity, point.equity)
        drawdown = 0.0 if peak_equity == 0 else (point.equity / peak_equity) - 1.0
        drawdown_curve.append(
            DrawdownPoint(
                trade_date=point.trade_date,
                drawdown=_round_metric(drawdown),
                peak_equity=peak_equity,
            )
        )
    return drawdown_curve


def calculate_annual_returns(
    equity_curve: Sequence[EquityPoint],
    trades: Sequence[TradeRecord],
) -> list[AnnualReturnPoint]:
    sorted_curve = _sort_equity_curve(equity_curve)
    if not sorted_curve:
        return []

    trades_by_year: dict[int, int] = defaultdict(int)
    for trade in trades:
        trades_by_year[trade.trade_date.year] += 1

    points_by_year: dict[int, list[EquityPoint]] = defaultdict(list)
    for point in sorted_curve:
        points_by_year[point.trade_date.year].append(point)

    annual_returns: list[AnnualReturnPoint] = []
    for year in sorted(points_by_year):
        yearly_points = points_by_year[year]
        start_equity = yearly_points[0].equity
        end_equity = yearly_points[-1].equity
        yearly_drawdown = min(point.drawdown for point in calculate_drawdown_curve(yearly_points))
        total_return = 0.0 if start_equity == 0 else (end_equity / start_equity) - 1.0
        annual_returns.append(
            AnnualReturnPoint(
                year=year,
                return_pct=_round_metric(total_return),
                max_drawdown_pct=_round_metric(yearly_drawdown),
                trade_count=trades_by_year.get(year, 0),
            )
        )
    return annual_returns


def _closed_trade_returns(trades: Sequence[TradeRecord]) -> list[float]:
    lots_by_symbol: dict[str, deque[tuple[int, float, float]]] = defaultdict(deque)
    closed_returns: list[float] = []
    for trade in sorted(trades, key=lambda item: (item.trade_date, item.symbol, item.side)):
        if trade.side == "buy":
            lots_by_symbol[trade.symbol].append((trade.shares, trade.price, trade.fees))
            continue

        remaining_shares = trade.shares
        sell_fee = trade.fees
        while remaining_shares > 0 and lots_by_symbol[trade.symbol]:
            buy_shares, buy_price, buy_fee = lots_by_symbol[trade.symbol][0]
            matched_shares = min(remaining_shares, buy_shares)
            cost_basis = (buy_price * matched_shares) + buy_fee
            proceeds = (trade.price * matched_shares) - sell_fee
            closed_returns.append(0.0 if cost_basis == 0 else (proceeds / cost_basis) - 1.0)
            remaining_shares -= matched_shares
            if matched_shares == buy_shares:
                lots_by_symbol[trade.symbol].popleft()
            else:
                lots_by_symbol[trade.symbol][0] = (buy_shares - matched_shares, buy_price, buy_fee)
            sell_fee = 0.0
    return closed_returns


def _annualized_return(start_date: date, end_date: date, total_return: float) -> float:
    span_days = max((end_date - start_date).days, 1)
    return ((1.0 + total_return) ** (365.0 / span_days)) - 1.0


def calculate_backtest_metrics(
    equity_curve: Sequence[EquityPoint],
    trades: Sequence[TradeRecord],
) -> BacktestMetrics:
    sorted_curve = _sort_equity_curve(equity_curve)
    if not sorted_curve:
        return BacktestMetrics(
            total_return_pct=0.0,
            annualized_return_pct=0.0,
            max_drawdown_pct=0.0,
            win_rate_pct=0.0,
            turnover_ratio=0.0,
            trade_count=len(trades),
        )

    start_equity = sorted_curve[0].equity
    end_equity = sorted_curve[-1].equity
    total_return = 0.0 if start_equity == 0 else (end_equity / start_equity) - 1.0
    annualized_return = _annualized_return(
        sorted_curve[0].trade_date,
        sorted_curve[-1].trade_date,
        total_return,
    )
    drawdown_curve = calculate_drawdown_curve(sorted_curve)
    max_drawdown = min((point.drawdown for point in drawdown_curve), default=0.0)
    closed_returns = _closed_trade_returns(trades)
    wins = sum(1 for trade_return in closed_returns if trade_return > 0)
    win_rate = 0.0 if not closed_returns else wins / len(closed_returns)
    average_equity = sum(point.equity for point in sorted_curve) / len(sorted_curve)
    total_turnover = sum(abs(trade.amount) for trade in trades)
    turnover_ratio = 0.0 if average_equity == 0 else total_turnover / average_equity
    return BacktestMetrics(
        total_return_pct=_round_metric(total_return),
        annualized_return_pct=_round_metric(annualized_return),
        max_drawdown_pct=_round_metric(max_drawdown),
        win_rate_pct=_round_metric(win_rate),
        turnover_ratio=_round_metric(turnover_ratio),
        trade_count=len(trades),
    )
