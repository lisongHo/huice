from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import json

from quantlab.config import AppPaths
from quantlab.schemas import MinuteBarRecord, SecurityStatusRecord
from quantlab.storage import ensure_state_dirs
from quantlab.strategies.builtin import default_strategy_config


def _paths(tmp_path: Path) -> AppPaths:
    paths = AppPaths.from_workspace(tmp_path)
    ensure_state_dirs(paths)
    return paths


def _minute_bar(symbol: str, trade_date: date, close: float) -> MinuteBarRecord:
    start_ts = datetime(trade_date.year, trade_date.month, trade_date.day, 14, 57, tzinfo=ZoneInfo("Asia/Shanghai"))
    return MinuteBarRecord(
        symbol=symbol,
        exchange="SZSE" if symbol.startswith(("00", "30")) else "SSE",
        trade_date=trade_date,
        bar_start_ts=start_ts,
        bar_end_ts=start_ts.replace(minute=58),
        open=close,
        high=close,
        low=close,
        close=close,
        volume=10_000,
        amount=close * 10_000,
    )


def test_end_to_end_single_run(tmp_path: Path) -> None:
    from app.ui.data_access import load_home_page_data
    from backtest.core.engine import run_backtest
    from data.ingest.publish import publish_minute_bars, publish_security_status_history
    from reports.artifacts import load_backtest_result, persist_backtest_result

    paths = _paths(tmp_path)
    trade_dates = [date(2022, 1, day) for day in range(3, 11)]
    closes = [10.4, 10.2, 10.0, 9.8, 9.7, 10.1, 10.3, 10.5]
    publish_minute_bars(
        paths,
        [_minute_bar("000001", trade_date, close) for trade_date, close in zip(trade_dates, closes, strict=True)],
        provider_name="local_bundle",
    )
    publish_security_status_history(
        paths,
        [
            SecurityStatusRecord(
                symbol="000001",
                effective_from=date(2022, 1, 1),
                effective_to=None,
                name="Ping An Bank",
                is_st=False,
                status_reason="normal",
            )
        ],
        provider_name="local_bundle",
    )

    result = run_backtest(paths, default_strategy_config(start_date="2022-01-03", end_date="2022-01-10"))
    manifest = persist_backtest_result(paths, result)
    loaded = load_backtest_result(paths, result.run_id)
    home_data = load_home_page_data(paths, limit=1)

    assert manifest.run_id == result.run_id
    assert loaded.run_id == result.run_id
    assert home_data.recent_runs[0].run_id == result.run_id
    assert home_data.recent_runs[0].metrics_path.endswith("metrics.json")


def test_end_to_end_local_seed_and_dry_run_flow_without_provider_credentials(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from app.ui.data_access import build_run_submission, load_home_page_data
    from scripts.run_single_backtest import run_single_backtest
    from scripts.seed_demo_data import seed_demo_data

    monkeypatch.chdir(tmp_path)

    paths = seed_demo_data(AppPaths.from_workspace(tmp_path))
    manifest = json.loads(run_single_backtest())
    home_data = load_home_page_data(paths, limit=1)
    submission = build_run_submission(default_strategy_config(start_date="2022-01-03", end_date="2022-01-10"), run_requested=False)

    assert home_data.recent_runs
    assert home_data.recent_runs[0].run_id == manifest["run_id"]
    assert (paths.runs_root / manifest["run_id"] / "manifest.json").exists()
    assert submission.run_requested is False
    assert submission.summary["run_requested"] is False
    assert paths.lake_root.exists()
