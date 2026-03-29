from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from quantlab.config import AppPaths
from quantlab.storage import ensure_state_dirs, readiness_artifact_path, readiness_root
from reports.artifacts import (
    load_latest_readiness_payload,
    load_recent_readiness_artifacts,
    persist_latest_readiness_payload,
    run_provider_readiness_check,
)


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


def test_readiness_payload_persists_a_timestamped_snapshot(tmp_path: Path, monkeypatch) -> None:
    import reports.artifacts as artifacts

    paths = _paths(tmp_path)
    payload = {
        "config": {
            "config_path": "/tmp/provider.toml",
            "api_url": "http://example.invalid",
            "token_visible": True,
            "reference_date": "2026-03-29",
        },
        "endpoint_probes": [{"api_name": "trade_cal", "status": "ok", "row_count": 1}],
    }

    monkeypatch.setattr(
        artifacts,
        "_readiness_snapshot_timestamp",
        lambda: datetime(2026, 3, 29, 1, 2, 3, 123456, tzinfo=timezone.utc),
        raising=False,
    )

    persisted = persist_latest_readiness_payload(paths, payload)
    snapshot_files = [path for path in readiness_root(paths).glob("*.json") if path.name != "latest.json"]

    assert persisted == readiness_artifact_path(paths)
    assert snapshot_files == [readiness_root(paths) / "20260329T010203123456Z.json"]
    assert json.loads(snapshot_files[0].read_text()) == payload


def test_load_recent_readiness_artifacts_returns_newest_snapshot_first(tmp_path: Path, monkeypatch) -> None:
    import reports.artifacts as artifacts

    paths = _paths(tmp_path)
    payloads = [
        {
            "config": {
                "config_path": "/tmp/provider.toml",
                "api_url": "http://example.invalid",
                "token_visible": True,
                "reference_date": "2026-03-28",
            },
            "endpoint_probes": [{"api_name": "trade_cal", "status": "ok", "row_count": 1}],
        },
        {
            "config": {
                "config_path": "/tmp/provider.toml",
                "api_url": "http://example.invalid",
                "token_visible": True,
                "reference_date": "2026-03-29",
            },
            "endpoint_probes": [{"api_name": "trade_cal", "status": "ok", "row_count": 2}],
        },
    ]
    timestamps = iter(
        [
            datetime(2026, 3, 29, 1, 2, 3, 123456, tzinfo=timezone.utc),
            datetime(2026, 3, 29, 1, 2, 4, 234567, tzinfo=timezone.utc),
        ]
    )

    monkeypatch.setattr(artifacts, "_readiness_snapshot_timestamp", lambda: next(timestamps), raising=False)

    first_persisted = persist_latest_readiness_payload(paths, payloads[0])
    second_persisted = persist_latest_readiness_payload(paths, payloads[1])
    recent = load_recent_readiness_artifacts(paths)

    assert first_persisted == readiness_artifact_path(paths)
    assert second_persisted == readiness_artifact_path(paths)
    assert load_latest_readiness_payload(paths) == payloads[1]
    assert [path.name for path, _ in recent] == [
        "20260329T010204234567Z.json",
        "20260329T010203123456Z.json",
    ]
    assert [payload for _, payload in recent] == payloads[::-1]


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
