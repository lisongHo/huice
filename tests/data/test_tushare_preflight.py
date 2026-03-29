from __future__ import annotations

import json
from dataclasses import dataclass
import sys
from typing import Any

import pandas as pd
import pytest

from data.providers import tushare_provider as provider_module
from data.providers.tushare_provider import TushareConfig, TushareConfigurationError, TushareHttpClient


@dataclass(frozen=True)
class _FakeResponse:
    payload: dict[str, Any]

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def _patch_tushare_response(monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]) -> None:
    monkeypatch.setattr(
        provider_module.request,
        "urlopen",
        lambda *args, **kwargs: _FakeResponse(payload),
    )


def test_tushare_http_client_reports_trade_cal_permission_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_tushare_response(monkeypatch, {"code": 2002, "msg": "权限不足"})

    client = TushareHttpClient(token="token", api_url="http://example.invalid", timeout_seconds=1)

    with pytest.raises(TushareConfigurationError, match="trade_cal.*Trade calendar access is unavailable"):
        client.query("trade_cal", params={"exchange": "SSE"}, fields=("exchange", "cal_date"))


def test_tushare_http_client_reports_stk_mins_permission_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_tushare_response(monkeypatch, {"code": 2002, "msg": "权限不足"})

    client = TushareHttpClient(token="token", api_url="http://example.invalid", timeout_seconds=1)

    with pytest.raises(TushareConfigurationError, match="stk_mins.*Minute-data permission is missing"):
        client.query(
            "stk_mins",
            params={"ts_code": "000001.SZ", "freq": "1min", "start_date": "2026-03-28 09:30:00", "end_date": "2026-03-28 15:30:00"},
            fields=("ts_code", "trade_time"),
        )


def test_tushare_readiness_helper_returns_structured_json(monkeypatch: pytest.MonkeyPatch) -> None:
    from data.providers.tushare_readiness import collect_tushare_readiness, tushare_readiness_to_dict

    class _FakeClient:
        def query(self, api_name: str, params=None, fields=None):
            if api_name == "trade_cal":
                return pd.DataFrame([{"exchange": "SSE", "cal_date": "20260328", "is_open": 1, "pretrade_date": "20260327"}])
            if api_name == "stock_basic":
                return pd.DataFrame([{"ts_code": "000001.SZ", "symbol": "000001"}])
            if api_name == "stk_mins":
                raise TushareConfigurationError(
                    "Tushare permission error for stk_mins: 权限不足. Minute-data permission is missing for this token."
                )
            raise AssertionError(f"unexpected api_name: {api_name}")

    @dataclass(frozen=True)
    class _FakeProvider:
        config: TushareConfig

        def _client(self) -> _FakeClient:
            return _FakeClient()

    provider = _FakeProvider(
        config=TushareConfig(token="token", api_url="http://example.invalid", universe_symbols=("000001",))
    )

    report = collect_tushare_readiness(provider=provider, reference_date="2026-03-28")
    payload = tushare_readiness_to_dict(report)

    assert payload["config"]["token_visible"] is True
    assert payload["config"]["api_url"] == "http://example.invalid"
    assert payload["endpoint_probes"][0]["api_name"] == "trade_cal"
    assert payload["endpoint_probes"][0]["status"] == "ok"
    assert payload["endpoint_probes"][1]["api_name"] == "stock_basic"
    assert payload["endpoint_probes"][1]["status"] == "ok"
    assert payload["endpoint_probes"][2]["api_name"] == "stk_mins"
    assert payload["endpoint_probes"][2]["status"] == "error"
    assert payload["endpoint_probes"][2]["error_message"].endswith("Minute-data permission is missing for this token.")


def test_tushare_preflight_cli_prints_json(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    from data.providers.tushare_readiness import (
        TushareEndpointProbeResult,
        TushareReadinessConfig,
        TushareReadinessReport,
    )
    from scripts import tushare_preflight as cli

    report = TushareReadinessReport(
        config=TushareReadinessConfig(
            config_path="/tmp/provider.toml",
            api_url="http://example.invalid",
            token_visible=True,
            reference_date="2026-03-28",
        ),
        endpoint_probes=(
            TushareEndpointProbeResult(api_name="trade_cal", status="ok", row_count=1),
            TushareEndpointProbeResult(api_name="stock_basic", status="ok", row_count=1, selected_symbol="000001"),
            TushareEndpointProbeResult(
                api_name="stk_mins",
                status="error",
                selected_symbol="000001",
                error_type="TushareConfigurationError",
                error_message="Minute-data permission is missing for this token.",
            ),
        ),
    )
    monkeypatch.setattr(cli, "collect_tushare_readiness", lambda **kwargs: report)
    monkeypatch.setattr(sys, "argv", ["tushare_preflight.py", "--reference-date", "2026-03-28"])

    assert cli.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["config"]["reference_date"] == "2026-03-28"
    assert payload["endpoint_probes"][2]["api_name"] == "stk_mins"


def test_tushare_preflight_cli_persists_latest_readiness_payload_and_prints_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from data.providers.tushare_readiness import (
        TushareEndpointProbeResult,
        TushareReadinessConfig,
        TushareReadinessReport,
        tushare_readiness_to_dict,
    )
    from scripts import tushare_preflight as cli

    report = TushareReadinessReport(
        config=TushareReadinessConfig(
            config_path="/tmp/provider.toml",
            api_url="http://example.invalid",
            token_visible=True,
            reference_date="2026-03-28",
        ),
        endpoint_probes=(
            TushareEndpointProbeResult(api_name="trade_cal", status="ok", row_count=1),
        ),
    )
    persisted: dict[str, object] = {}

    def _fake_persist(paths, payload):
        persisted["paths"] = paths
        persisted["payload"] = payload
        return "/tmp/latest.json"

    monkeypatch.setattr(cli, "collect_tushare_readiness", lambda **kwargs: report)
    monkeypatch.setattr(cli, "persist_latest_readiness_payload", _fake_persist, raising=False)
    monkeypatch.setattr(sys, "argv", ["tushare_preflight.py", "--reference-date", "2026-03-28", "--persist"])

    assert cli.main() == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload == json.loads(json.dumps(tushare_readiness_to_dict(report), default=str))
    assert persisted["payload"] == tushare_readiness_to_dict(report)
    assert persisted["paths"] is not None
