from __future__ import annotations

from collections import defaultdict

from quantlab.schemas import AnnualReturnPoint, BacktestMetrics, DrawdownPoint, EquityPoint, TradeRecord


def build_drawdown_curve(equity_curve: list[EquityPoint]) -> list[DrawdownPoint]:
    peak = 0.0
    points: list[DrawdownPoint] = []
    for point in equity_curve:
        peak = max(peak, point.equity)
        drawdown = 0.0 if peak <= 0 else (point.equity / peak) - 1
        points.append(
            DrawdownPoint(
                trade_date=point.trade_date,
                drawdown=drawdown,
                peak_equity=peak,
            )
        )
    return points


def build_annual_returns(
    equity_curve: list[EquityPoint],
    trades: list[TradeRecord],
) -> list[AnnualReturnPoint]:
    if not equity_curve:
        return []

    equity_by_year: dict[int, list[EquityPoint]] = defaultdict(list)
    trade_count_by_year: dict[int, int] = defaultdict(int)
    for point in equity_curve:
        equity_by_year[point.trade_date.year].append(point)
    for trade in trades:
        trade_count_by_year[trade.trade_date.year] += 1

    results: list[AnnualReturnPoint] = []
    for year in sorted(equity_by_year):
        year_points = equity_by_year[year]
        start_equity = year_points[0].equity
        end_equity = year_points[-1].equity
        return_pct = 0.0 if start_equity <= 0 else ((end_equity / start_equity) - 1) * 100
        year_drawdowns = build_drawdown_curve(year_points)
        max_drawdown_pct = abs(min((point.drawdown for point in year_drawdowns), default=0.0)) * 100
        results.append(
            AnnualReturnPoint(
                year=year,
                return_pct=return_pct,
                max_drawdown_pct=max_drawdown_pct,
                trade_count=trade_count_by_year.get(year, 0),
            )
        )
    return results


def build_metrics(
    initial_cash: float,
    equity_curve: list[EquityPoint],
    trades: list[TradeRecord],
    realized_pnls: list[float],
    total_turnover: float,
) -> BacktestMetrics:
    if not equity_curve:
        return BacktestMetrics(
            total_return_pct=0.0,
            annualized_return_pct=0.0,
            max_drawdown_pct=0.0,
            win_rate_pct=0.0,
            turnover_ratio=0.0,
            trade_count=0,
        )

    start_equity = initial_cash
    end_equity = equity_curve[-1].equity
    total_return_pct = 0.0 if start_equity <= 0 else ((end_equity / start_equity) - 1) * 100
    elapsed_days = max((equity_curve[-1].trade_date - equity_curve[0].trade_date).days, 1)
    years = elapsed_days / 365.25
    if start_equity > 0 and end_equity > 0 and years > 0:
        annualized_return_pct = (((end_equity / start_equity) ** (1 / years)) - 1) * 100
    else:
        annualized_return_pct = 0.0
    drawdown_curve = build_drawdown_curve(equity_curve)
    max_drawdown_pct = abs(min((point.drawdown for point in drawdown_curve), default=0.0)) * 100
    win_rate_pct = (
        (sum(1 for pnl in realized_pnls if pnl > 0) / len(realized_pnls)) * 100 if realized_pnls else 0.0
    )
    average_equity = sum(point.equity for point in equity_curve) / len(equity_curve)
    turnover_ratio = 0.0 if average_equity <= 0 else total_turnover / average_equity
    return BacktestMetrics(
        total_return_pct=total_return_pct,
        annualized_return_pct=annualized_return_pct,
        max_drawdown_pct=max_drawdown_pct,
        win_rate_pct=win_rate_pct,
        turnover_ratio=turnover_ratio,
        trade_count=len(trades),
    )
