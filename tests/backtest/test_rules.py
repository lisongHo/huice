from __future__ import annotations

from datetime import date

from quantlab.schemas import BacktestRunConfig, ExecutionMode


def test_a_share_rules_enforce_board_lot_t_plus_one_and_no_overlap() -> None:
    from backtest.core.broker import simulate_order
    from backtest.models import HoldingState, MarketContext, OrderRequest

    config = BacktestRunConfig.for_builtin_strategy(
        name="builtin_consecutive_down_rsi",
        start_date="2022-01-03",
        end_date="2022-01-10",
        execution_mode=ExecutionMode.LAST_5M_VWAP,
    )

    buy_order = OrderRequest(symbol="000001", trade_date=date(2022, 1, 6), side="buy", target_cash=123_456)
    buy_fill = simulate_order(
        order=buy_order,
        holding=None,
        context=MarketContext(
            is_suspended=False,
            is_st=False,
            at_up_limit=False,
            at_down_limit=False,
            lot_size=config.portfolio.board_lot_size,
            execution_price=9.87,
            available_cash=200_000,
        ),
        config=config,
    )
    same_day_sell = simulate_order(
        order=OrderRequest(symbol="000001", trade_date=date(2022, 1, 6), side="sell", target_cash=0),
        holding=HoldingState(symbol="000001", shares=buy_fill.shares, entry_trade_date=date(2022, 1, 6)),
        context=MarketContext(
            is_suspended=False,
            is_st=False,
            at_up_limit=False,
            at_down_limit=False,
            lot_size=config.portfolio.board_lot_size,
            execution_price=9.95,
            available_cash=0,
        ),
        config=config,
    )
    duplicate_entry = simulate_order(
        order=buy_order,
        holding=HoldingState(symbol="000001", shares=buy_fill.shares, entry_trade_date=date(2022, 1, 6)),
        context=MarketContext(
            is_suspended=False,
            is_st=False,
            at_up_limit=False,
            at_down_limit=False,
            lot_size=config.portfolio.board_lot_size,
            execution_price=9.87,
            available_cash=200_000,
        ),
        config=config,
    )

    assert buy_fill.status == "filled"
    assert buy_fill.shares % 100 == 0
    assert same_day_sell.status == "rejected_t_plus_one"
    assert duplicate_entry.status == "rejected_existing_position"


def test_buy_and_sell_block_when_price_limit_or_suspension_or_st_filter_applies() -> None:
    from backtest.core.broker import simulate_order
    from backtest.models import MarketContext, OrderRequest

    config = BacktestRunConfig.for_builtin_strategy(
        name="builtin_consecutive_down_rsi",
        start_date="2022-01-03",
        end_date="2022-01-10",
    )
    buy_order = OrderRequest(symbol="300001", trade_date=date(2022, 1, 6), side="buy", target_cash=50_000)

    blocked_contexts = [
        MarketContext(
            is_suspended=True,
            is_st=False,
            at_up_limit=False,
            at_down_limit=False,
            lot_size=config.portfolio.board_lot_size,
            execution_price=19.5,
            available_cash=100_000,
        ),
        MarketContext(
            is_suspended=False,
            is_st=True,
            at_up_limit=False,
            at_down_limit=False,
            lot_size=config.portfolio.board_lot_size,
            execution_price=19.5,
            available_cash=100_000,
        ),
        MarketContext(
            is_suspended=False,
            is_st=False,
            at_up_limit=True,
            at_down_limit=False,
            lot_size=config.portfolio.board_lot_size,
            execution_price=19.5,
            available_cash=100_000,
        ),
    ]

    statuses = [
        simulate_order(order=buy_order, holding=None, context=context, config=config).status
        for context in blocked_contexts
    ]

    assert statuses == ["rejected_suspension", "rejected_st", "rejected_price_limit"]
