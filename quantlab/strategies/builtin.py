from __future__ import annotations

from quantlab.schemas import BacktestRunConfig, ExecutionMode, StrategyParams


BUILTIN_STRATEGY_NAME = "builtin_consecutive_down_rsi"


def default_strategy_params() -> StrategyParams:
    return StrategyParams()


def default_strategy_config(
    start_date: str,
    end_date: str,
    execution_mode: ExecutionMode = ExecutionMode.LAST_5M_VWAP,
) -> BacktestRunConfig:
    return BacktestRunConfig.for_builtin_strategy(
        name=BUILTIN_STRATEGY_NAME,
        start_date=start_date,
        end_date=end_date,
        execution_mode=execution_mode,
    )
