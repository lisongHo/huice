from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import streamlit as st

from quantlab.schemas import BacktestRunConfig, ExecutionMode, StrategyParams
from quantlab.strategies.builtin import BUILTIN_STRATEGY_NAME, default_strategy_config


@dataclass(slots=True)
class BacktestSubmissionDraft:
    submitted: bool
    config: BacktestRunConfig
    payload: dict[str, Any]
    summary: dict[str, Any]


@dataclass(slots=True)
class ScanRequestDraft:
    submitted: bool
    payload: dict[str, Any]
    summary: dict[str, Any]


def _execution_mode_options() -> list[ExecutionMode]:
    return [
        ExecutionMode.LAST_5M_VWAP,
        ExecutionMode.CLOSE_PROXY,
        ExecutionMode.NEXT_OPEN_CONTROL,
    ]


def render_single_backtest_form(
    default_config: BacktestRunConfig | None = None,
) -> BacktestSubmissionDraft:
    config = default_config or default_strategy_config("2022-01-01", "2022-01-31")
    with st.form("single_backtest_config", clear_on_submit=False):
        st.caption(f"Built-in strategy: {BUILTIN_STRATEGY_NAME}")
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input("Start date", value=config.start_date)
            initial_cash = st.number_input(
                "Initial cash",
                min_value=10_000.0,
                value=float(config.portfolio.initial_cash),
                step=50_000.0,
                format="%.2f",
            )
            max_positions = st.number_input(
                "Max positions",
                min_value=1,
                max_value=100,
                value=int(config.portfolio.max_positions),
                step=1,
            )
            board_lot_size = st.number_input(
                "Board lot size",
                min_value=1,
                value=int(config.portfolio.board_lot_size),
                step=1,
            )
            execution_mode = st.selectbox(
                "Execution mode",
                options=_execution_mode_options(),
                index=_execution_mode_options().index(config.execution.mode),
                format_func=lambda mode: mode.value,
            )
        with col2:
            end_date = st.date_input("End date", value=config.end_date)
            consecutive_down_days = st.number_input(
                "Consecutive down days",
                min_value=1,
                max_value=20,
                value=int(config.strategy_params.consecutive_down_days),
                step=1,
            )
            rsi_window = st.number_input(
                "RSI window",
                min_value=2,
                max_value=60,
                value=int(config.strategy_params.rsi_window),
                step=1,
            )
            rsi_threshold = st.number_input(
                "RSI threshold",
                min_value=0.0,
                max_value=100.0,
                value=float(config.strategy_params.rsi_threshold),
                step=0.5,
            )
            hold_days = st.number_input(
                "Hold days",
                min_value=1,
                max_value=60,
                value=int(config.strategy_params.hold_days),
                step=1,
            )

        st.subheader("Risk and rule defaults")
        rule_col1, rule_col2 = st.columns(2)
        with rule_col1:
            allow_overlap = st.checkbox(
                "Allow same-symbol overlap",
                value=bool(config.portfolio.allow_same_symbol_overlap),
            )
            equal_weight = st.checkbox("Equal weight", value=bool(config.portfolio.equal_weight))
            enforce_t_plus_one = st.checkbox("Enforce T+1", value=bool(config.rules.enforce_t_plus_one))
            enforce_price_limits = st.checkbox(
                "Enforce price limits",
                value=bool(config.rules.enforce_price_limits),
            )
        with rule_col2:
            enforce_suspension = st.checkbox(
                "Enforce suspension filter",
                value=bool(config.rules.enforce_suspension),
            )
            exclude_st = st.checkbox("Exclude ST", value=bool(config.rules.exclude_st))
            exclude_new_listed_days = st.number_input(
                "Exclude new listed days",
                min_value=0,
                max_value=30,
                value=int(config.rules.exclude_new_listed_days),
                step=1,
            )

        submitted = st.form_submit_button("Create run request", type="primary")

    strategy_params = StrategyParams(
        consecutive_down_days=int(consecutive_down_days),
        rsi_window=int(rsi_window),
        rsi_threshold=float(rsi_threshold),
        hold_days=int(hold_days),
    )
    updated_config = BacktestRunConfig(
        strategy_name=config.strategy_name,
        start_date=start_date,
        end_date=end_date,
        execution=config.execution.model_copy(update={"mode": execution_mode}),
        portfolio=config.portfolio.model_copy(
            update={
                "initial_cash": float(initial_cash),
                "max_positions": int(max_positions),
                "board_lot_size": int(board_lot_size),
                "allow_same_symbol_overlap": bool(allow_overlap),
                "equal_weight": bool(equal_weight),
            }
        ),
        fees=config.fees,
        rules=config.rules.model_copy(
            update={
                "enforce_t_plus_one": bool(enforce_t_plus_one),
                "enforce_price_limits": bool(enforce_price_limits),
                "enforce_suspension": bool(enforce_suspension),
                "exclude_st": bool(exclude_st),
                "exclude_new_listed_days": int(exclude_new_listed_days),
            }
        ),
        universe=config.universe,
        strategy_params=strategy_params,
    )
    payload = updated_config.model_dump(mode="json")
    summary = {
        "strategy_name": updated_config.strategy_name,
        "window": f"{updated_config.start_date} to {updated_config.end_date}",
        "execution_mode": updated_config.execution.mode.value,
        "initial_cash": updated_config.portfolio.initial_cash,
        "max_positions": updated_config.portfolio.max_positions,
        "hold_days": updated_config.strategy_params.hold_days,
        "rsi_window": updated_config.strategy_params.rsi_window,
        "rsi_threshold": updated_config.strategy_params.rsi_threshold,
    }
    return BacktestSubmissionDraft(
        submitted=submitted,
        config=updated_config,
        payload=payload,
        summary=summary,
    )


def render_parameter_scan_form(
    default_config: BacktestRunConfig | None = None,
) -> ScanRequestDraft:
    config = default_config or default_strategy_config("2022-01-01", "2022-01-31")
    with st.form("parameter_scan_config", clear_on_submit=False):
        st.caption(f"Built-in strategy family: {BUILTIN_STRATEGY_NAME}")
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input("Scan start date", value=config.start_date, key="scan_start_date")
            end_date = st.date_input("Scan end date", value=config.end_date, key="scan_end_date")
            execution_mode = st.selectbox(
                "Scan execution mode",
                options=_execution_mode_options(),
                index=_execution_mode_options().index(config.execution.mode),
                format_func=lambda mode: mode.value,
                key="scan_execution_mode",
            )
        with col2:
            consecutive_down_days = st.text_input(
                "Consecutive down days grid",
                value="2,3,4",
                help="Comma-separated integer values.",
            )
            rsi_thresholds = st.text_input(
                "RSI threshold grid",
                value="25,30,35",
                help="Comma-separated float values.",
            )
            hold_days = st.text_input(
                "Hold days grid",
                value="2,3,5",
                help="Comma-separated integer values.",
            )
        notes = st.text_area(
            "Scan notes",
            value="Prepared from the Streamlit workbench. Execution remains explicit and artifact-first.",
            height=96,
        )
        submitted = st.form_submit_button("Prepare scan request", type="primary")

    down_day_values = _parse_number_grid(consecutive_down_days, cast_type=int)
    rsi_values = _parse_number_grid(rsi_thresholds, cast_type=float)
    hold_day_values = _parse_number_grid(hold_days, cast_type=int)
    combination_count = len(down_day_values) * len(rsi_values) * len(hold_day_values)
    payload = {
        "strategy_name": config.strategy_name,
        "start_date": str(start_date),
        "end_date": str(end_date),
        "execution_mode": execution_mode.value,
        "grid": {
            "consecutive_down_days": down_day_values,
            "rsi_threshold": rsi_values,
            "hold_days": hold_day_values,
        },
        "notes": notes,
    }
    summary = {
        "strategy_name": config.strategy_name,
        "execution_mode": execution_mode.value,
        "window": f"{start_date} to {end_date}",
        "parameter_count": 3,
        "combination_count": combination_count,
    }
    return ScanRequestDraft(
        submitted=submitted,
        payload=payload,
        summary=summary,
    )


def _parse_number_grid(raw_value: str, *, cast_type: type[int] | type[float]) -> list[int] | list[float]:
    values: list[int] | list[float] = []
    for part in raw_value.split(","):
        piece = part.strip()
        if not piece:
            continue
        values.append(cast_type(piece))
    return values
