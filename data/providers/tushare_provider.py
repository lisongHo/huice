from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib import error, request

import pandas as pd

from data.providers.base import ProviderCapabilities
from data.providers.local_bundle import canonicalize_symbol, infer_exchange

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.11+ includes tomllib
    tomllib = None

DEFAULT_TUSHARE_API_URL = "http://api.tushare.pro"
DEFAULT_STOCK_PREFIXES: tuple[str, ...] = ("00", "30", "60")
MINUTE_FIELDS: tuple[str, ...] = (
    "ts_code",
    "trade_time",
    "open",
    "close",
    "high",
    "low",
    "vol",
    "amount",
)


class TushareConfigurationError(RuntimeError):
    """Raised when the provider cannot be configured for a real sync."""


class TushareRequestError(RuntimeError):
    """Raised when Tushare rejects or fails a request."""


@dataclass(frozen=True)
class TushareConfig:
    token: str | None = None
    api_url: str = DEFAULT_TUSHARE_API_URL
    timeout_seconds: float = 30.0
    minute_freq: str = "1min"
    minute_chunk_days: int = 20
    refresh_lookback_open_days: int = 5
    maintenance_lookback_open_days: int = 10
    prefixes: tuple[str, ...] = DEFAULT_STOCK_PREFIXES
    universe_symbols: tuple[str, ...] = ()
    universe_file: Path | None = None

    @property
    def has_token(self) -> bool:
        return bool(self.token and self.token.strip())


@dataclass(frozen=True)
class TushareHttpClient:
    token: str
    api_url: str = DEFAULT_TUSHARE_API_URL
    timeout_seconds: float = 30.0

    def query(
        self,
        api_name: str,
        params: Mapping[str, Any] | None = None,
        fields: Sequence[str] | None = None,
    ) -> pd.DataFrame:
        payload = {
            "api_name": api_name,
            "token": self.token,
            "params": dict(params or {}),
            "fields": ",".join(fields) if fields else "",
        }
        encoded = json.dumps(payload).encode("utf-8")
        http_request = request.Request(
            self.api_url,
            data=encoded,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with request.urlopen(http_request, timeout=self.timeout_seconds) as response:
                raw_payload = response.read().decode("utf-8")
        except error.HTTPError as exc:  # pragma: no cover - network unavailable in CI/sandbox
            details = exc.read().decode("utf-8", errors="ignore")
            raise TushareRequestError(
                f"Tushare HTTP {exc.code} for {api_name}: {details or exc.reason}"
            ) from exc
        except error.URLError as exc:  # pragma: no cover - network unavailable in CI/sandbox
            raise TushareRequestError(
                f"Unable to reach Tushare API at {self.api_url}: {exc.reason}"
            ) from exc

        payload_object = json.loads(raw_payload)
        code = int(payload_object.get("code", -1))
        if code != 0:
            message = str(payload_object.get("msg") or "unknown Tushare error")
            if code == -2001 or "token" in message.lower():
                raise TushareConfigurationError(
                    f"Tushare rejected the token for {api_name}: {message}. "
                    "Set TUSHARE_TOKEN or provide it in the config file."
                )
            if code == 2002 or "权限" in message or "积分" in message:
                raise TushareConfigurationError(
                    f"Tushare permission error for {api_name}: {message}. "
                    "Historical stock minutes require an activated token and separate minute-data permission."
                )
            raise TushareRequestError(f"Tushare request failed for {api_name}: {message}")

        data = payload_object.get("data") or {}
        response_fields = list(data.get("fields") or list(fields or ()))
        items = data.get("items") or []
        if not items:
            return pd.DataFrame(columns=response_fields)
        return pd.DataFrame(items, columns=response_fields)


@dataclass(frozen=True)
class TushareProProvider:
    config: TushareConfig
    name: str = "tushare_pro"

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_minute_bars=True,
            supports_security_status_history=False,
            supports_price_limits=False,
            supports_suspensions=False,
        )

    def get_minute_bars(
        self,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
        symbols: Sequence[str] | None = None,
    ) -> pd.DataFrame:
        normalized_symbols = restrict_stock_symbols(symbols or self.config.universe_symbols, prefixes=self.config.prefixes)
        if not normalized_symbols:
            raise TushareConfigurationError(
                "Tushare minute sync needs an explicit stock universe. "
                "Pass symbols via config, --symbols, or sync security_master first."
            )

        start_value, end_value = minute_window_to_strings(start_date, end_date)
        frames: list[pd.DataFrame] = []
        client = self._client()

        for symbol in normalized_symbols:
            raw_frame = client.query(
                "stk_mins",
                params={
                    "ts_code": tushare_ts_code(symbol),
                    "freq": self.config.minute_freq,
                    "start_date": start_value,
                    "end_date": end_value,
                },
                fields=MINUTE_FIELDS,
            )
            if raw_frame.empty:
                continue
            normalized = raw_frame.rename(
                columns={
                    "ts_code": "raw_ts_code",
                    "trade_time": "bar_start_ts",
                    "vol": "volume",
                }
            ).copy()
            normalized["symbol"] = symbol
            normalized["exchange"] = infer_exchange(symbol)
            normalized["bar_start_ts"] = _normalize_minute_timestamp_series(normalized["bar_start_ts"])
            normalized["bar_end_ts"] = normalized["bar_start_ts"] + pd.Timedelta(minutes=1)
            normalized["trade_date"] = normalized["bar_start_ts"].dt.date
            for numeric_column in ("open", "close", "high", "low", "volume", "amount"):
                normalized[numeric_column] = pd.to_numeric(normalized[numeric_column], errors="coerce")
            normalized["pre_close"] = pd.NA
            volume = pd.to_numeric(normalized["volume"], errors="coerce")
            amount = pd.to_numeric(normalized["amount"], errors="coerce")
            normalized["vwap"] = amount.where(volume != 0, pd.NA) / volume.where(volume != 0, pd.NA)
            normalized["is_synthetic_bar"] = False
            frames.append(normalized)

        if not frames:
            return pd.DataFrame(columns=_minute_dataset_columns())

        result = pd.concat(frames, ignore_index=True)
        return result[_minute_dataset_columns()].sort_values(["symbol", "bar_start_ts"]).reset_index(drop=True)

    def get_security_master(self) -> pd.DataFrame:
        client = self._client()
        frame = client.query(
            "stock_basic",
            params={"exchange": "", "list_status": "L"},
            fields=("ts_code", "symbol", "name", "market", "exchange", "list_date", "delist_date"),
        )
        if frame.empty:
            return pd.DataFrame(columns=_security_master_columns())

        result = frame.copy()
        result["symbol"] = result["symbol"].map(canonicalize_symbol)
        result = result[result["symbol"].map(lambda value: value.startswith(self.config.prefixes))]
        result["exchange"] = result["symbol"].map(infer_exchange)
        result["board"] = result["market"].fillna("unknown")
        result["is_st"] = result["name"].astype(str).str.upper().str.startswith(("ST", "*ST"))
        return result[_security_master_columns()].reset_index(drop=True)

    def get_security_status_history(
        self,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
        symbols: Sequence[str] | None = None,
    ) -> pd.DataFrame:
        return pd.DataFrame(
            columns=["symbol", "effective_from", "effective_to", "name", "is_st", "status_reason"]
        )

    def get_trade_calendar(
        self,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> pd.DataFrame:
        client = self._client()
        params = {
            "exchange": "SSE",
            "start_date": _date_to_yyyymmdd(start_date),
            "end_date": _date_to_yyyymmdd(end_date),
        }
        frame = client.query(
            "trade_cal",
            params={key: value for key, value in params.items() if value},
            fields=("exchange", "cal_date", "is_open", "pretrade_date"),
        )
        if frame.empty:
            return pd.DataFrame(columns=["trade_date", "is_open", "prev_trade_date", "next_trade_date"])

        result = frame.rename(columns={"cal_date": "trade_date", "pretrade_date": "prev_trade_date"}).copy()
        result["trade_date"] = pd.to_datetime(result["trade_date"], format="%Y%m%d", errors="coerce").dt.date
        result["prev_trade_date"] = pd.to_datetime(
            result["prev_trade_date"], format="%Y%m%d", errors="coerce"
        ).dt.date
        result["is_open"] = result["is_open"].astype(int)

        next_lookup: dict[date, date | None] = {}
        open_dates = [row for row in result.loc[result["is_open"] == 1, "trade_date"].tolist() if isinstance(row, date)]
        for index, trade_day in enumerate(open_dates):
            next_lookup[trade_day] = open_dates[index + 1] if index + 1 < len(open_dates) else None
        result["next_trade_date"] = result["trade_date"].map(next_lookup)
        return result[["trade_date", "is_open", "prev_trade_date", "next_trade_date"]].sort_values(
            ["trade_date"]
        ).reset_index(drop=True)

    def get_adjustment_factors(
        self,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
        symbols: Sequence[str] | None = None,
    ) -> pd.DataFrame:
        return pd.DataFrame(columns=["symbol", "ex_date", "adj_factor", "action_type"])

    def get_suspensions(
        self,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
        symbols: Sequence[str] | None = None,
    ) -> pd.DataFrame:
        return pd.DataFrame(columns=["symbol", "trade_date", "is_suspended"])

    def get_price_limits(
        self,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
        symbols: Sequence[str] | None = None,
    ) -> pd.DataFrame:
        return pd.DataFrame(columns=["symbol", "trade_date", "pre_close", "up_limit", "down_limit"])

    def _client(self) -> TushareHttpClient:
        if not self.config.has_token:
            raise TushareConfigurationError(
                "Tushare token is missing. Set TUSHARE_TOKEN or create configs/provider.toml from configs/provider.example.toml."
            )
        return TushareHttpClient(
            token=self.config.token or "",
            api_url=self.config.api_url,
            timeout_seconds=self.config.timeout_seconds,
        )


def load_tushare_config(
    config_path: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> TushareConfig:
    env = env or os.environ
    resolved_path = resolve_provider_config_path(config_path=config_path, env=env)
    config_payload: dict[str, Any] = {}
    if resolved_path and resolved_path.exists():
        if tomllib is None:  # pragma: no cover - Python <3.11 fallback
            raise TushareConfigurationError("tomllib is unavailable; use Python 3.11+ to read the provider config.")
        config_payload = tomllib.loads(resolved_path.read_text())

    tushare_section = dict(config_payload.get("tushare", {}))
    universe_section = dict(config_payload.get("universe", {}))
    resolved_universe_file = _resolve_optional_path(resolved_path, universe_section.get("file"))
    configured_symbols = tuple(
        restrict_stock_symbols(
            list(universe_section.get("symbols") or ())
            + list(load_symbols_from_json(resolved_universe_file) if resolved_universe_file else ()),
            prefixes=tuple(universe_section.get("prefixes") or DEFAULT_STOCK_PREFIXES),
        )
    )

    return TushareConfig(
        token=_coalesce_str(env.get("TUSHARE_TOKEN"), tushare_section.get("token")),
        api_url=_coalesce_str(env.get("TUSHARE_API_URL"), tushare_section.get("api_url")) or DEFAULT_TUSHARE_API_URL,
        timeout_seconds=float(env.get("TUSHARE_TIMEOUT_SECONDS") or tushare_section.get("timeout_seconds") or 30.0),
        minute_freq=_coalesce_str(env.get("TUSHARE_MINUTE_FREQ"), tushare_section.get("minute_freq")) or "1min",
        minute_chunk_days=int(
            env.get("TUSHARE_MINUTE_CHUNK_DAYS") or tushare_section.get("minute_chunk_days") or 20
        ),
        refresh_lookback_open_days=int(
            env.get("TUSHARE_REFRESH_LOOKBACK_OPEN_DAYS")
            or tushare_section.get("refresh_lookback_open_days")
            or 5
        ),
        maintenance_lookback_open_days=int(
            env.get("TUSHARE_MAINTENANCE_LOOKBACK_OPEN_DAYS")
            or tushare_section.get("maintenance_lookback_open_days")
            or 10
        ),
        prefixes=tuple(universe_section.get("prefixes") or DEFAULT_STOCK_PREFIXES),
        universe_symbols=configured_symbols,
        universe_file=resolved_universe_file,
    )


def resolve_provider_config_path(
    config_path: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> Path | None:
    env = env or os.environ
    if config_path is not None:
        return Path(config_path).expanduser().resolve()
    if env.get("TUSHARE_CONFIG"):
        return Path(env["TUSHARE_CONFIG"]).expanduser().resolve()

    candidate = Path.cwd() / "configs" / "provider.toml"
    if candidate.exists():
        return candidate.resolve()
    return None


def build_tushare_provider(
    config_path: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> TushareProProvider:
    return TushareProProvider(config=load_tushare_config(config_path=config_path, env=env))


def load_symbols_from_json(path: Path) -> tuple[str, ...]:
    payload = json.loads(path.read_text())
    if isinstance(payload, list):
        symbols = payload
    elif isinstance(payload, dict):
        symbols = payload.get("symbols") or []
    else:
        raise TushareConfigurationError(f"unsupported universe file payload in {path}")
    return tuple(restrict_stock_symbols(symbols))


def restrict_stock_symbols(
    symbols: Sequence[str] | None,
    prefixes: Sequence[str] = DEFAULT_STOCK_PREFIXES,
) -> list[str]:
    if not symbols:
        return []

    allowed_prefixes = tuple(prefixes)
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_symbol in symbols:
        symbol = canonicalize_symbol(raw_symbol)
        if not symbol.startswith(allowed_prefixes):
            continue
        if symbol in seen:
            continue
        seen.add(symbol)
        normalized.append(symbol)
    return sorted(normalized)


def tushare_ts_code(symbol: str) -> str:
    normalized = canonicalize_symbol(symbol)
    exchange = "SZ" if normalized.startswith(("00", "30")) else "SH"
    return f"{normalized}.{exchange}"


def minute_window_to_strings(
    start_date: date | str | None,
    end_date: date | str | None,
) -> tuple[str, str]:
    if start_date is None or end_date is None:
        raise TushareConfigurationError("minute sync requires both start_date and end_date")

    start_value = pd.Timestamp(start_date)
    end_value = pd.Timestamp(end_date)
    if end_value < start_value:
        raise TushareConfigurationError("end_date must be on or after start_date")

    start_dt = datetime.combine(start_value.date(), datetime.min.time()).replace(hour=9)
    end_dt = datetime.combine(end_value.date(), datetime.min.time()).replace(hour=15, minute=30)
    return start_dt.strftime("%Y-%m-%d %H:%M:%S"), end_dt.strftime("%Y-%m-%d %H:%M:%S")


def _date_to_yyyymmdd(value: date | str | None) -> str | None:
    if value is None:
        return None
    return pd.Timestamp(value).strftime("%Y%m%d")


def _resolve_optional_path(config_path: Path | None, raw_path: object) -> Path | None:
    if not raw_path:
        return None
    candidate = Path(str(raw_path)).expanduser()
    if candidate.is_absolute() or config_path is None:
        return candidate.resolve()
    return (config_path.parent / candidate).resolve()


def _coalesce_str(*values: object) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _normalize_minute_timestamp_series(values: pd.Series) -> pd.Series:
    timestamps = pd.to_datetime(values)
    if timestamps.dt.tz is None:
        return timestamps.dt.tz_localize("Asia/Shanghai")
    return timestamps.dt.tz_convert("Asia/Shanghai")


def _minute_dataset_columns() -> list[str]:
    return [
        "symbol",
        "exchange",
        "trade_date",
        "bar_start_ts",
        "bar_end_ts",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "pre_close",
        "vwap",
        "is_synthetic_bar",
    ]


def _security_master_columns() -> list[str]:
    return [
        "symbol",
        "exchange",
        "list_date",
        "delist_date",
        "board",
        "name",
        "is_st",
    ]
