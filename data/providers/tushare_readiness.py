from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Callable, Mapping, Sequence

import pandas as pd

from data.providers.tushare_provider import (
    TushareConfigurationError,
    TushareProProvider,
    TushareRequestError,
    build_tushare_provider,
    minute_window_to_strings,
    resolve_provider_config_path,
    restrict_stock_symbols,
    tushare_ts_code,
)


@dataclass(frozen=True)
class TushareReadinessConfig:
    config_path: str | None
    api_url: str | None
    token_visible: bool
    reference_date: str
    error_message: str | None = None


@dataclass(frozen=True)
class TushareEndpointProbeResult:
    api_name: str
    status: str
    row_count: int | None = None
    selected_symbol: str | None = None
    error_type: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class TushareReadinessReport:
    config: TushareReadinessConfig
    endpoint_probes: tuple[TushareEndpointProbeResult, ...]


def collect_tushare_readiness(
    config_path: Path | None = None,
    env: Mapping[str, str] | None = None,
    provider: TushareProProvider | None = None,
    reference_date: date | str | None = None,
    probe_symbols: Sequence[str] | None = None,
) -> TushareReadinessReport:
    normalized_reference_date = pd.Timestamp(reference_date or date.today()).date()
    resolved_config = resolve_provider_config_path(config_path=config_path, env=env)
    resolved_config_path = str(resolved_config) if resolved_config else None

    if provider is None:
        try:
            provider = build_tushare_provider(config_path=config_path, env=env)
        except Exception as exc:  # pragma: no cover - configuration path failure is covered via tests
            return TushareReadinessReport(
                config=TushareReadinessConfig(
                    config_path=resolved_config_path,
                    api_url=None,
                    token_visible=False,
                    reference_date=normalized_reference_date.isoformat(),
                    error_message=str(exc),
                ),
                endpoint_probes=(),
            )

    config = provider.config
    if not config.has_token:
        return TushareReadinessReport(
            config=TushareReadinessConfig(
                config_path=resolved_config_path,
                api_url=config.api_url,
                token_visible=False,
                reference_date=normalized_reference_date.isoformat(),
            ),
            endpoint_probes=_skipped_probes(reason="Tushare token is missing"),
        )

    client = provider._client()
    minute_start, minute_end = minute_window_to_strings(normalized_reference_date, normalized_reference_date)

    trade_cal = _probe_query(
        api_name="trade_cal",
        run=lambda: client.query(
            "trade_cal",
            params={
                "exchange": "SSE",
                "start_date": normalized_reference_date.strftime("%Y%m%d"),
                "end_date": normalized_reference_date.strftime("%Y%m%d"),
            },
            fields=("exchange", "cal_date", "is_open", "pretrade_date"),
        ),
    )
    stock_basic = _probe_query(
        api_name="stock_basic",
        run=lambda: client.query(
            "stock_basic",
            params={"exchange": "", "list_status": "L"},
            fields=("ts_code", "symbol"),
        ),
    )
    selected_symbol = _select_probe_symbol(stock_basic.row_count, stock_basic.selected_symbol, probe_symbols)
    stk_mins = _probe_query(
        api_name="stk_mins",
        run=lambda: client.query(
            "stk_mins",
            params={
                "ts_code": tushare_ts_code(selected_symbol),
                "freq": config.minute_freq,
                "start_date": minute_start,
                "end_date": minute_end,
            },
            fields=("ts_code", "trade_time"),
        ),
        selected_symbol=selected_symbol,
    )

    return TushareReadinessReport(
        config=TushareReadinessConfig(
            config_path=resolved_config_path,
            api_url=config.api_url,
            token_visible=True,
            reference_date=normalized_reference_date.isoformat(),
        ),
        endpoint_probes=(trade_cal, stock_basic, stk_mins),
    )


def tushare_readiness_to_dict(report: TushareReadinessReport) -> dict[str, object]:
    return asdict(report)


def _probe_query(
    api_name: str,
    run: Callable[[], pd.DataFrame],
    selected_symbol: str | None = None,
) -> TushareEndpointProbeResult:
    try:
        frame = run()
    except (TushareConfigurationError, TushareRequestError) as exc:
        return TushareEndpointProbeResult(
            api_name=api_name,
            status="error",
            selected_symbol=selected_symbol,
            error_type=exc.__class__.__name__,
            error_message=str(exc),
        )
    except Exception as exc:  # pragma: no cover - defensive guard for CLI diagnostics
        return TushareEndpointProbeResult(
            api_name=api_name,
            status="error",
            selected_symbol=selected_symbol,
            error_type=exc.__class__.__name__,
            error_message=str(exc),
        )

    row_count = len(frame.index)
    probe_symbol = selected_symbol
    if api_name == "stock_basic" and row_count > 0 and "symbol" in frame.columns:
        probe_symbol = str(frame.iloc[0]["symbol"]).strip() or None

    return TushareEndpointProbeResult(
        api_name=api_name,
        status="ok",
        row_count=row_count,
        selected_symbol=probe_symbol,
    )


def _select_probe_symbol(
    stock_basic_row_count: int | None,
    stock_basic_symbol: str | None,
    probe_symbols: Sequence[str] | None,
) -> str:
    if stock_basic_row_count and stock_basic_symbol:
        return stock_basic_symbol

    normalized = restrict_stock_symbols(probe_symbols)
    if normalized:
        return normalized[0]
    return "000001"


def _skipped_probes(reason: str) -> tuple[TushareEndpointProbeResult, ...]:
    return (
        TushareEndpointProbeResult(
            api_name="trade_cal",
            status="skipped",
            error_message=reason,
        ),
        TushareEndpointProbeResult(
            api_name="stock_basic",
            status="skipped",
            error_message=reason,
        ),
        TushareEndpointProbeResult(
            api_name="stk_mins",
            status="skipped",
            selected_symbol="000001",
            error_message=reason,
        ),
    )
