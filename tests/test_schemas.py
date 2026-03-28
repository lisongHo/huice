from quantlab.schemas import BacktestRunConfig, ExecutionMode


def test_backtest_run_config_defaults_match_v0_1() -> None:
    config = BacktestRunConfig.for_builtin_strategy(
        name="builtin_consecutive_down_rsi",
        start_date="2022-01-01",
        end_date="2022-01-10",
    )

    assert config.execution.mode == ExecutionMode.LAST_5M_VWAP
    assert config.portfolio.initial_cash == 1_000_000
    assert config.portfolio.max_positions == 10
    assert config.portfolio.board_lot_size == 100
    assert config.portfolio.allow_same_symbol_overlap is False
