from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from datetime import date

from quantlab.config import AppPaths
from quantlab.schemas import BacktestResult, BacktestRunConfig, ExecutionMode

from backtest.core.broker import build_buy_fill, build_sell_fill
from backtest.core.execution import target_execution_date
from backtest.core.features import build_daily_bars, compute_daily_features, select_entry_candidates
from backtest.core.ledger import apply_buy, apply_sell, initialize_ledger, record_equity
from backtest.core.universe import (
    advance_trade_date,
    eligible_symbols_for_date,
    load_market_data,
    trading_dates_in_range,
)
from backtest.metrics import build_annual_returns, build_drawdown_curve, build_metrics
from backtest.models import CandidateSignal, PendingOrder, PreparedBacktestData


def _process_pending_orders(
    state,
    bundle,
    config,
    trade_date: date,
    pending_orders: dict[date, list[PendingOrder]],
) -> None:
    orders = pending_orders.pop(trade_date, [])
    if not orders:
        return

    for side in ("sell", "buy"):
        for order in [item for item in orders if item.side == side]:
            if side == "sell":
                position = state.positions.get(order.symbol)
                if position is None:
                    continue
                fill = build_sell_fill(bundle, config, position, trade_date)
                if fill is not None:
                    apply_sell(state, fill)
            else:
                if order.symbol in state.positions:
                    continue
                budget = float(order.budget or 0.0)
                if budget <= 0:
                    continue
                fill = build_buy_fill(bundle, config, order.symbol, trade_date, budget=min(budget, state.cash))
                if fill is None:
                    continue
                scheduled_exit_date = advance_trade_date(bundle, fill.trade_date, config.strategy_params.hold_days)
                meta = bundle.symbol_meta.get(order.symbol, {})
                apply_buy(
                    state,
                    fill,
                    scheduled_exit_date=scheduled_exit_date,
                    board=str(meta.get("board", "")) or None,
                    exchange=str(meta.get("exchange", "")) or None,
                )


def _schedule_entry_orders(
    bundle,
    config,
    pending_orders: dict[date, list[PendingOrder]],
    trade_date: date,
    candidates: list[CandidateSignal],
    available_slots: int,
    cash: float,
) -> None:
    if available_slots <= 0 or cash <= 0 or not candidates:
        return
    execution_date = target_execution_date(bundle, trade_date, config.execution.mode)
    if execution_date is None:
        return

    target_count = min(available_slots, len(candidates))
    budget_per_position = cash / target_count if target_count > 0 else 0.0
    if config.execution.mode == ExecutionMode.NEXT_OPEN_CONTROL:
        for candidate in candidates[:target_count]:
            pending_orders[execution_date].append(
                PendingOrder(
                    symbol=candidate.symbol,
                    side="buy",
                    decision_date=trade_date,
                    execution_date=execution_date,
                    budget=budget_per_position,
                )
            )
        return

    return None


def _schedule_exit_order(
    bundle,
    config,
    pending_orders: dict[date, list[PendingOrder]],
    trade_date: date,
    symbol: str,
) -> None:
    execution_date = target_execution_date(bundle, trade_date, config.execution.mode)
    if execution_date is None or config.execution.mode != ExecutionMode.NEXT_OPEN_CONTROL:
        return
    already_scheduled = any(
        order.symbol == symbol and order.side == "sell"
        for orders in pending_orders.values()
        for order in orders
    )
    if not already_scheduled:
        pending_orders[execution_date].append(
            PendingOrder(
                symbol=symbol,
                side="sell",
                decision_date=trade_date,
                execution_date=execution_date,
            )
        )


def _mark_prices(bundle, trade_date: date) -> dict[str, float]:
    prices: dict[str, float] = {}
    for (symbol, bar_date), frame in bundle.minute_lookup.items():
        if bar_date != trade_date or frame.empty:
            continue
        prices[symbol] = float(frame.sort_values("bar_start_ts").iloc[-1]["close"])
    return prices


def _empty_result(config: BacktestRunConfig) -> BacktestResult:
    from quantlab.schemas import BacktestMetrics

    return BacktestResult(
        run_id=config.run_id,
        config=config,
        metrics=BacktestMetrics(
            total_return_pct=0.0,
            annualized_return_pct=0.0,
            max_drawdown_pct=0.0,
            win_rate_pct=0.0,
            turnover_ratio=0.0,
            trade_count=0,
        ),
        equity_curve=[],
        drawdown_curve=[],
        trades=[],
        annual_returns=[],
    )


def prepare_backtest_data(paths: AppPaths, config: BacktestRunConfig) -> PreparedBacktestData:
    bundle = load_market_data(paths, config)
    trade_dates = tuple(trading_dates_in_range(bundle, config.start_date, config.end_date))
    daily_bars = build_daily_bars(bundle)
    return PreparedBacktestData(
        bundle=bundle,
        trade_dates=trade_dates,
        daily_bars=daily_bars,
    )


def run_backtest_with_prepared_data(
    prepared_data: PreparedBacktestData,
    config: BacktestRunConfig,
) -> BacktestResult:
    bundle = prepared_data.bundle
    trade_dates = list(prepared_data.trade_dates)
    if not trade_dates or bundle.minute_bars.empty:
        return _empty_result(config)

    feature_frame = compute_daily_features(prepared_data.daily_bars, config)
    state = initialize_ledger(config.portfolio.initial_cash)
    pending_orders: dict[date, list[PendingOrder]] = defaultdict(list)

    for trade_date in trade_dates:
        _process_pending_orders(state, bundle, config, trade_date, pending_orders)

        due_positions = [
            position
            for position in state.positions.values()
            if position.scheduled_exit_date is not None and position.scheduled_exit_date <= trade_date
        ]
        for position in sorted(due_positions, key=lambda item: item.symbol):
            if config.execution.mode == ExecutionMode.NEXT_OPEN_CONTROL:
                _schedule_exit_order(bundle, config, pending_orders, trade_date, position.symbol)
                continue
            fill = build_sell_fill(bundle, config, position, trade_date)
            if fill is not None:
                apply_sell(state, fill)

        available_slots = max(config.portfolio.max_positions - len(state.positions), 0)
        eligible_symbols = eligible_symbols_for_date(bundle, config, trade_date)
        candidates = select_entry_candidates(
            bundle=bundle,
            config=config,
            feature_frame=feature_frame,
            decision_date=trade_date,
            eligible_symbols=eligible_symbols,
            held_symbols=set(state.positions.keys()),
        )
        if available_slots > 0 and candidates:
            if config.execution.mode == ExecutionMode.NEXT_OPEN_CONTROL:
                _schedule_entry_orders(
                    bundle=bundle,
                    config=config,
                    pending_orders=pending_orders,
                    trade_date=trade_date,
                    candidates=candidates,
                    available_slots=available_slots,
                    cash=state.cash,
                )
            else:
                target_count = min(available_slots, len(candidates))
                budget_per_position = state.cash / target_count if target_count > 0 else 0.0
                for candidate in candidates[:target_count]:
                    if candidate.symbol in state.positions:
                        continue
                    fill = build_buy_fill(bundle, config, candidate.symbol, trade_date, budget_per_position)
                    if fill is None:
                        continue
                    fill = replace(
                        fill,
                        notes=f"{fill.notes or config.execution.mode.value}; T-1 features from {candidate.feature_date}",
                    )
                    scheduled_exit_date = advance_trade_date(bundle, fill.trade_date, config.strategy_params.hold_days)
                    meta = bundle.symbol_meta.get(candidate.symbol, {})
                    apply_buy(
                        state,
                        fill,
                        scheduled_exit_date=scheduled_exit_date,
                        board=str(meta.get("board", "")) or None,
                        exchange=str(meta.get("exchange", "")) or None,
                    )

        record_equity(state, trade_date, _mark_prices(bundle, trade_date))

    drawdown_curve = build_drawdown_curve(state.equity_curve)
    annual_returns = build_annual_returns(state.equity_curve, state.trades)
    metrics = build_metrics(
        initial_cash=config.portfolio.initial_cash,
        equity_curve=state.equity_curve,
        trades=state.trades,
        realized_pnls=state.realized_pnls,
        total_turnover=state.total_turnover,
    )
    return BacktestResult(
        run_id=config.run_id,
        config=config,
        metrics=metrics,
        equity_curve=state.equity_curve,
        drawdown_curve=drawdown_curve,
        trades=state.trades,
        annual_returns=annual_returns,
    )


def run_backtest(
    paths: AppPaths | BacktestRunConfig,
    config: BacktestRunConfig | AppPaths,
) -> BacktestResult:
    if isinstance(paths, BacktestRunConfig) and isinstance(config, AppPaths):
        paths, config = config, paths
    elif not isinstance(paths, AppPaths) or not isinstance(config, BacktestRunConfig):
        raise TypeError("run_backtest expects (paths, config) or (config, paths)")

    prepared_data = prepare_backtest_data(paths, config)
    return run_backtest_with_prepared_data(prepared_data, config)
