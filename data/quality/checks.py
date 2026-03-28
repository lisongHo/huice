from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time
from typing import Mapping
from uuid import uuid4

import pandas as pd


@dataclass(frozen=True)
class QualityCheckResult:
    dataset_name: str
    check_name: str
    severity: str
    status: str
    details: str
    validation_run_id: str = field(default_factory=lambda: uuid4().hex)


def run_quality_checks(
    dataset_name: str,
    frame: pd.DataFrame,
    reference_frames: Mapping[str, pd.DataFrame] | None = None,
) -> list[QualityCheckResult]:
    reference_frames = reference_frames or {}

    if dataset_name == "minute_bars":
        return _minute_bar_checks(frame, reference_frames)
    if dataset_name == "security_status_history":
        return _security_status_history_checks(frame)
    if dataset_name == "price_limits":
        return _price_limit_checks(frame, reference_frames)
    if dataset_name == "adjustment_factors":
        return _adjustment_factor_checks(frame)

    return [
        _result(
            dataset_name=dataset_name,
            check_name="dataset_not_empty_or_allowed_empty",
            severity="warning",
            status="passed" if frame is not None else "skipped",
            details="no dataset-specific validation configured",
        )
    ]


def validate_minute_bars(records: list[object]) -> list[QualityCheckResult]:
    frame = pd.DataFrame(
        [
            record.model_dump(mode="json") if hasattr(record, "model_dump") else dict(record)
            for record in records
        ]
    )
    if not frame.empty:
        frame["bar_start_ts"] = pd.to_datetime(frame["bar_start_ts"], utc=True)
        if "bar_end_ts" in frame.columns:
            frame["bar_end_ts"] = pd.to_datetime(frame["bar_end_ts"], utc=True)
    results = _minute_bar_checks(frame, {})
    alias_map = {
        "duplicate_minute_keys": "duplicate_minute_key",
        "ohlc_relationships": "illegal_ohlc",
        "non_negative_volume_amount": "negative_volume_or_amount",
    }
    aliased_results: list[QualityCheckResult] = []
    for result in results:
        check_name = alias_map.get(result.check_name, result.check_name)
        aliased_results.append(
            QualityCheckResult(
                dataset_name=result.dataset_name,
                check_name=check_name,
                severity=result.severity,
                status=result.status,
                details=result.details,
            )
        )
    return aliased_results


def _minute_bar_checks(
    frame: pd.DataFrame,
    reference_frames: Mapping[str, pd.DataFrame],
) -> list[QualityCheckResult]:
    results = [
        _check_duplicate_minute_keys(frame),
        _check_ohlc_relationships(frame),
        _check_non_negative_volume_amount(frame),
        _check_minute_session_times(frame),
        _check_minute_count_matches_session_rules(frame),
        _check_security_live_on_trade_date(frame, reference_frames.get("security_master")),
        _check_suspensions_not_trading(frame, reference_frames.get("suspensions")),
    ]
    return results


def _security_status_history_checks(frame: pd.DataFrame) -> list[QualityCheckResult]:
    if frame.empty:
        return [_result("security_status_history", "status_history_present", "warning", "passed", "dataset empty")]

    result = frame.sort_values(["symbol", "effective_from"]).copy()
    overlaps: list[str] = []
    for _, group in result.groupby("symbol", sort=False):
        previous_end = None
        previous_from = None
        symbol = str(group.iloc[0]["symbol"])
        for row in group.itertuples(index=False):
            if previous_end is not None and pd.notna(previous_end) and row.effective_from <= previous_end:
                overlaps.append(f"{symbol}:{previous_from}->{previous_end} overlaps {row.effective_from}")
            previous_end = row.effective_to
            previous_from = row.effective_from

    return [
        _result(
            "security_status_history",
            "no_overlapping_effective_windows",
            "error",
            "failed" if overlaps else "passed",
            "; ".join(overlaps[:5]) if overlaps else "dated security status history is queryable",
        )
    ]


def _price_limit_checks(
    frame: pd.DataFrame,
    reference_frames: Mapping[str, pd.DataFrame],
) -> list[QualityCheckResult]:
    if frame.empty:
        return [_result("price_limits", "price_limit_alignment", "warning", "passed", "dataset empty")]

    status_history = reference_frames.get("security_status_history")
    security_master = reference_frames.get("security_master")
    mismatches: list[str] = []

    for row in frame.itertuples(index=False):
        is_st = _resolve_is_st(row.symbol, row.trade_date, status_history, security_master)
        limit_pct = 0.05 if is_st else 0.2 if str(row.symbol).startswith("30") else 0.10
        expected_up = round(float(row.pre_close) * (1 + limit_pct), 2)
        expected_down = round(float(row.pre_close) * (1 - limit_pct), 2)
        if abs(float(row.up_limit) - expected_up) > 0.02 or abs(float(row.down_limit) - expected_down) > 0.02:
            mismatches.append(
                f"{row.symbol}@{row.trade_date}: expected ({expected_down}, {expected_up})"
            )

    return [
        _result(
            "price_limits",
            "price_limit_alignment",
            "error",
            "failed" if mismatches else "passed",
            "; ".join(mismatches[:5]) if mismatches else "limits align with pre_close and board/ST rules",
        )
    ]


def _adjustment_factor_checks(frame: pd.DataFrame) -> list[QualityCheckResult]:
    if frame.empty:
        return [_result("adjustment_factors", "adjustment_factor_actions", "warning", "passed", "dataset empty")]

    invalid_rows = frame[(frame["adj_factor"] <= 0) | frame["action_type"].astype(str).str.strip().eq("")]
    return [
        _result(
            "adjustment_factors",
            "adjustment_factor_actions",
            "error",
            "failed" if not invalid_rows.empty else "passed",
            "all adjustment-factor rows require positive factors and action types"
            if invalid_rows.empty
            else f"invalid rows: {len(invalid_rows.index)}",
        )
    ]


def _check_duplicate_minute_keys(frame: pd.DataFrame) -> QualityCheckResult:
    if frame.empty:
        return _result("minute_bars", "duplicate_minute_keys", "error", "passed", "dataset empty")

    duplicate_mask = frame.duplicated(subset=["symbol", "bar_start_ts"], keep=False)
    duplicates = frame.loc[duplicate_mask, ["symbol", "bar_start_ts"]]
    return _result(
        "minute_bars",
        "duplicate_minute_keys",
        "error",
        "failed" if not duplicates.empty else "passed",
        duplicates.head().to_dict("records").__repr__() if not duplicates.empty else "canonical minute key is unique",
    )


def _check_ohlc_relationships(frame: pd.DataFrame) -> QualityCheckResult:
    if frame.empty:
        return _result("minute_bars", "ohlc_relationships", "error", "passed", "dataset empty")

    invalid = frame[
        (frame["high"] < frame[["open", "close", "low"]].max(axis=1))
        | (frame["low"] > frame[["open", "close", "high"]].min(axis=1))
    ]
    return _result(
        "minute_bars",
        "ohlc_relationships",
        "error",
        "failed" if not invalid.empty else "passed",
        f"invalid rows: {len(invalid.index)}" if not invalid.empty else "open/high/low/close relationships are valid",
    )


def _check_non_negative_volume_amount(frame: pd.DataFrame) -> QualityCheckResult:
    if frame.empty:
        return _result("minute_bars", "non_negative_volume_amount", "error", "passed", "dataset empty")

    invalid = frame[(frame["volume"] < 0) | (frame["amount"] < 0)]
    return _result(
        "minute_bars",
        "non_negative_volume_amount",
        "error",
        "failed" if not invalid.empty else "passed",
        f"invalid rows: {len(invalid.index)}" if not invalid.empty else "volume and amount are non-negative",
    )


def _check_minute_session_times(frame: pd.DataFrame) -> QualityCheckResult:
    if frame.empty:
        return _result("minute_bars", "valid_session_times", "error", "passed", "dataset empty")

    local_times = frame["bar_start_ts"].dt.tz_convert("Asia/Shanghai").dt.time
    valid = local_times.map(_is_valid_session_time)
    invalid_rows = frame.loc[~valid, ["symbol", "bar_start_ts"]]
    return _result(
        "minute_bars",
        "valid_session_times",
        "error",
        "failed" if not invalid_rows.empty else "passed",
        invalid_rows.head().to_dict("records").__repr__() if not invalid_rows.empty else "all bars are inside continuous session windows",
    )


def _check_minute_count_matches_session_rules(frame: pd.DataFrame) -> QualityCheckResult:
    if frame.empty:
        return _result("minute_bars", "minute_count_matches_session_rules", "warning", "passed", "dataset empty")

    counts = frame.groupby(["symbol", "trade_date"]).size().reset_index(name="bar_count")
    invalid = counts[counts["bar_count"] != 240]
    return _result(
        "minute_bars",
        "minute_count_matches_session_rules",
        "warning",
        "failed" if not invalid.empty else "passed",
        invalid.head().to_dict("records").__repr__() if not invalid.empty else "each symbol/trade_date has 240 bars",
    )


def _check_security_live_on_trade_date(
    frame: pd.DataFrame,
    security_master: pd.DataFrame | None,
) -> QualityCheckResult:
    if frame.empty or security_master is None or security_master.empty:
        return _result(
            "minute_bars",
            "security_live_on_trade_date",
            "warning",
            "passed",
            "security master unavailable for cross-check",
        )

    master = security_master[["symbol", "list_date", "delist_date"]].copy()
    master["list_date"] = pd.to_datetime(master["list_date"]).dt.date
    master["delist_date"] = pd.to_datetime(master["delist_date"], errors="coerce").dt.date
    merged = frame[["symbol", "trade_date"]].drop_duplicates().merge(master, on="symbol", how="left")
    invalid = merged[
        merged["list_date"].isna()
        | (merged["trade_date"] < merged["list_date"])
        | (merged["delist_date"].notna() & (merged["trade_date"] > merged["delist_date"]))
    ]
    return _result(
        "minute_bars",
        "security_live_on_trade_date",
        "error",
        "failed" if not invalid.empty else "passed",
        invalid.head().to_dict("records").__repr__() if not invalid.empty else "all minute bars map to live securities",
    )


def _check_suspensions_not_trading(
    frame: pd.DataFrame,
    suspensions: pd.DataFrame | None,
) -> QualityCheckResult:
    if frame.empty or suspensions is None or suspensions.empty:
        return _result(
            "minute_bars",
            "suspended_days_not_trading",
            "warning",
            "passed",
            "suspension dataset unavailable for cross-check",
        )

    suspended = suspensions[suspensions["is_suspended"] == True][["symbol", "trade_date"]].copy()
    if suspended.empty:
        return _result("minute_bars", "suspended_days_not_trading", "warning", "passed", "no suspended days")

    grouped = frame.groupby(["symbol", "trade_date"], as_index=False).agg(
        bar_count=("symbol", "size"),
        total_volume=("volume", "sum"),
    )
    merged = grouped.merge(suspended, on=["symbol", "trade_date"], how="inner")
    invalid = merged[(merged["bar_count"] > 0) & (merged["total_volume"] > 0)]
    return _result(
        "minute_bars",
        "suspended_days_not_trading",
        "error",
        "failed" if not invalid.empty else "passed",
        invalid.head().to_dict("records").__repr__() if not invalid.empty else "suspended days do not trade",
    )


def _resolve_is_st(
    symbol: str,
    trade_date: object,
    status_history: pd.DataFrame | None,
    security_master: pd.DataFrame | None,
) -> bool:
    target_ts = pd.Timestamp(trade_date).normalize()
    if status_history is not None and not status_history.empty:
        history = status_history[status_history["symbol"] == symbol].copy()
        if not history.empty:
            history["effective_from"] = pd.to_datetime(history["effective_from"]).dt.normalize()
            history["effective_to"] = pd.to_datetime(history["effective_to"], errors="coerce").dt.normalize()
            matched = history[
                (history["effective_from"] <= target_ts)
                & (history["effective_to"].isna() | (history["effective_to"] >= target_ts))
            ]
            if not matched.empty:
                return bool(matched.iloc[-1]["is_st"])

    if security_master is not None and not security_master.empty:
        matched_master = security_master[security_master["symbol"] == symbol]
        if not matched_master.empty:
            return bool(matched_master.iloc[0]["is_st"])

    return False


def _is_valid_session_time(value: time) -> bool:
    morning_start = time(9, 30)
    morning_end = time(11, 29)
    afternoon_start = time(13, 0)
    afternoon_end = time(14, 59)
    return (morning_start <= value <= morning_end) or (afternoon_start <= value <= afternoon_end)


def _result(
    dataset_name: str,
    check_name: str,
    severity: str,
    status: str,
    details: str,
) -> QualityCheckResult:
    return QualityCheckResult(
        dataset_name=dataset_name,
        check_name=check_name,
        severity=severity,
        status=status,
        details=details,
    )
