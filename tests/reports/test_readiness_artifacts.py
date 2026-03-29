from __future__ import annotations

import json
from pathlib import Path

from quantlab.config import AppPaths
from quantlab.storage import ensure_state_dirs, readiness_artifact_path, readiness_root
from reports.artifacts import load_latest_readiness_payload, persist_latest_readiness_payload, run_provider_readiness_check


def _paths(tmp_path: Path) -> AppPaths:
    paths = AppPaths.from_workspace(tmp_path)
    ensure_state_dirs(paths)
    return paths


def test_readiness_payload_persists_and_loads_latest_json(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    payload = {
        "config": {
            "config_path": "/tmp/provider.toml",
            "api_url": "http://example.invalid",
            "token_visible": True,
            "reference_date": "2026-03-28",
        },
        "endpoint_probes": [{"api_name": "trade_cal", "status": "ok", "row_count": 1}],
    }

    persisted = persist_latest_readiness_payload(paths, payload)
    loaded = load_latest_readiness_payload(paths)

    assert persisted == readiness_artifact_path(paths)
    assert persisted == readiness_root(paths) / "latest.json"
    assert json.loads(persisted.read_text()) == payload
    assert loaded == payload


def test_run_provider_readiness_check_persists_latest_payload(monkeypatch, tmp_path: Path) -> None:
    import reports.artifacts as artifacts

    paths = _paths(tmp_path)
    payload = {
        "config": {
            "config_path": str(tmp_path / "configs" / "provider.toml"),
            "api_url": "http://example.invalid",
            "token_visible": True,
            "reference_date": "2026-03-29",
        },
        "endpoint_probes": [
            {"api_name": "trade_cal", "status": "ok", "row_count": 1},
            {"api_name": "stock_basic", "status": "ok", "row_count": 2},
            {"api_name": "stk_mins", "status": "error", "error_message": "Minute-data permission is missing for this token."},
        ],
    }

    monkeypatch.setattr(artifacts, "collect_tushare_readiness", lambda **kwargs: object())
    monkeypatch.setattr(artifacts, "tushare_readiness_to_dict", lambda report: payload)

    result = run_provider_readiness_check(paths=paths, reference_date="2026-03-29")

    assert result == payload
    assert load_latest_readiness_payload(paths) == payload
