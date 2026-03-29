from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
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


@dataclass(slots=True)
class SyncCockpitSubmissionDraft:
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
        st.caption(f"内置策略：{BUILTIN_STRATEGY_NAME}")
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input("开始日期", value=config.start_date)
            initial_cash = st.number_input(
                "初始资金",
                min_value=10_000.0,
                value=float(config.portfolio.initial_cash),
                step=50_000.0,
                format="%.2f",
            )
            max_positions = st.number_input(
                "最大持仓数",
                min_value=1,
                max_value=100,
                value=int(config.portfolio.max_positions),
                step=1,
            )
            board_lot_size = st.number_input(
                "整手股数",
                min_value=1,
                value=int(config.portfolio.board_lot_size),
                step=1,
            )
            execution_mode = st.selectbox(
                "执行模式",
                options=_execution_mode_options(),
                index=_execution_mode_options().index(config.execution.mode),
                format_func=lambda mode: mode.value,
            )
        with col2:
            end_date = st.date_input("结束日期", value=config.end_date)
            consecutive_down_days = st.number_input(
                "连续下跌天数",
                min_value=1,
                max_value=20,
                value=int(config.strategy_params.consecutive_down_days),
                step=1,
            )
            rsi_window = st.number_input(
                "RSI 窗口",
                min_value=2,
                max_value=60,
                value=int(config.strategy_params.rsi_window),
                step=1,
            )
            rsi_threshold = st.number_input(
                "RSI 阈值",
                min_value=0.0,
                max_value=100.0,
                value=float(config.strategy_params.rsi_threshold),
                step=0.5,
            )
            hold_days = st.number_input(
                "持有天数",
                min_value=1,
                max_value=60,
                value=int(config.strategy_params.hold_days),
                step=1,
            )

        st.subheader("风控与交易规则")
        rule_col1, rule_col2 = st.columns(2)
        with rule_col1:
            allow_overlap = st.checkbox(
                "允许同票重叠持仓",
                value=bool(config.portfolio.allow_same_symbol_overlap),
            )
            equal_weight = st.checkbox("等权配置", value=bool(config.portfolio.equal_weight))
            enforce_t_plus_one = st.checkbox("启用 T+1", value=bool(config.rules.enforce_t_plus_one))
            enforce_price_limits = st.checkbox(
                "启用涨跌停限制",
                value=bool(config.rules.enforce_price_limits),
            )
        with rule_col2:
            enforce_suspension = st.checkbox(
                "启用停牌过滤",
                value=bool(config.rules.enforce_suspension),
            )
            exclude_st = st.checkbox("排除 ST", value=bool(config.rules.exclude_st))
            exclude_new_listed_days = st.number_input(
                "排除新上市天数",
                min_value=0,
                max_value=30,
                value=int(config.rules.exclude_new_listed_days),
                step=1,
            )

        submitted = st.form_submit_button("准备回测请求", type="primary")

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
        st.caption(f"内置策略族：{BUILTIN_STRATEGY_NAME}")
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input("扫描开始日期", value=config.start_date, key="scan_start_date")
            end_date = st.date_input("扫描结束日期", value=config.end_date, key="scan_end_date")
            execution_mode = st.selectbox(
                "扫描执行模式",
                options=_execution_mode_options(),
                index=_execution_mode_options().index(config.execution.mode),
                format_func=lambda mode: mode.value,
                key="scan_execution_mode",
            )
        with col2:
            consecutive_down_days = st.text_input(
                "连续下跌天数网格",
                value="2,3,4",
                help="用逗号分隔整数值。",
            )
            rsi_thresholds = st.text_input(
                "RSI 阈值网格",
                value="25,30,35",
                help="用逗号分隔浮点值。",
            )
            hold_days = st.text_input(
                "持有天数网格",
                value="2,3,5",
                help="用逗号分隔整数值。",
            )
        notes = st.text_area(
            "扫描备注",
            value="由 Streamlit 工作台准备。执行保持显式触发，结果优先写入 artifact。",
            height=96,
        )
        submitted = st.form_submit_button("准备扫描请求", type="primary")

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


def render_sync_cockpit_form() -> SyncCockpitSubmissionDraft:
    workflow_options = ["backfill", "daily-refresh", "weekly-maintenance"]
    today = date.today()
    with st.form("sync_cockpit_config", clear_on_submit=False):
        st.caption("先准备同步请求，再从右侧显式触发 dry-run 规划或真实执行。")
        workflow = st.selectbox(
            "同步模式",
            options=workflow_options,
            index=0,
            format_func=lambda value: value.replace("-", " ").title(),
        )
        col1, col2 = st.columns(2)
        with col1:
            if workflow == "backfill":
                start_date = st.date_input("开始日期", value=today - timedelta(days=4))
            else:
                start_date = None
            end_date = st.date_input("结束日期", value=today)
        with col2:
            config_path = st.text_input("配置文件路径", value="", help="可选的 Tushare provider TOML 配置路径。")
            symbols_text = st.text_area(
                "股票列表",
                value="",
                height=96,
                help="可选，使用逗号分隔 A 股股票代码。",
            )

        submitted = st.form_submit_button("准备同步请求", type="primary")

    symbols = [value.strip() for value in symbols_text.split(",") if value.strip()]
    payload: dict[str, Any] = {
        "workflow": workflow,
        "config_path": config_path.strip() or None,
        "symbols": symbols,
    }
    if workflow == "backfill":
        payload["start_date"] = str(start_date)
        payload["end_date"] = str(end_date)
        summary = {
            "workflow": "backfill",
            "window": f"{start_date} 至 {end_date}",
            "symbol_count": len(symbols),
            "config_path": config_path.strip() or "默认 provider 配置",
        }
    else:
        payload["end_date"] = str(end_date)
        summary = {
            "workflow": workflow,
            "window": f"截至 {end_date}",
            "symbol_count": len(symbols),
            "config_path": config_path.strip() or "默认 provider 配置",
        }

    return SyncCockpitSubmissionDraft(
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
