from __future__ import annotations

import argparse
import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from data.ingest.sync import (
    build_provider,
    json_dump,
    resolve_open_trade_dates,
    resolve_symbol_universe,
    scan_minute_bar_gaps,
    validate_minute_data,
)
from data.providers.tushare_provider import TushareConfigurationError
from quantlab.config import AppPaths


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate local minute-bar data and optionally run an explicit gap scan."
    )
    parser.add_argument("--start-date", help="Inclusive start date in YYYY-MM-DD format.")
    parser.add_argument("--end-date", help="Inclusive end date in YYYY-MM-DD format.")
    parser.add_argument("--config", help="Optional provider config TOML path for gap-scan universe planning.")
    parser.add_argument(
        "--symbols",
        nargs="*",
        help="Optional symbol subset for validation. Symbols remain restricted to 00/30/60 prefixes.",
    )
    parser.add_argument(
        "--gap-scan",
        action="store_true",
        help="Compare stored minute bars against the expected symbol x open-date matrix.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero when validation finds failed error checks or gap issues.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    paths = AppPaths.from_workspace()
    if args.gap_scan and (not args.start_date or not args.end_date):
        print("--gap-scan requires both --start-date and --end-date.", file=sys.stderr)
        return 2
    try:
        validation = validate_minute_data(
            paths=paths,
            start_date=args.start_date,
            end_date=args.end_date,
            symbols=args.symbols,
        )

        gap_scan_payload = None
        if args.gap_scan:
            provider = build_provider(config_path=args.config)
            symbols = resolve_symbol_universe(paths=paths, provider=provider, symbols=args.symbols, plan_only=True)
            trade_dates = resolve_open_trade_dates(
                paths=paths,
                provider=provider,
                start_date=args.start_date,
                end_date=args.end_date,
                plan_only=True,
            )
            gap_scan_payload = scan_minute_bar_gaps(paths=paths, trade_dates=trade_dates, expected_symbols=symbols)
    except TushareConfigurationError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception as exc:  # pragma: no cover - thin CLI wrapper
        print(str(exc), file=sys.stderr)
        return 1

    payload = {"validation": validation}
    if gap_scan_payload is not None:
        payload["gap_scan"] = {
            "expected_trade_dates": gap_scan_payload.expected_trade_dates,
            "expected_symbol_count": gap_scan_payload.expected_symbol_count,
            "issue_count": gap_scan_payload.issue_count,
            "affected_trade_dates": gap_scan_payload.affected_trade_dates,
            "issues": [
                {
                    "trade_date": issue.trade_date,
                    "symbol": issue.symbol,
                    "actual_bars": issue.actual_bars,
                    "expected_bars": issue.expected_bars,
                }
                for issue in gap_scan_payload.issues
            ],
        }

    print(json_dump(payload))

    if not args.strict:
        return 0

    has_validation_errors = bool(validation["failed_error_checks"])
    has_gap_issues = gap_scan_payload is not None and gap_scan_payload.issue_count > 0
    return 1 if has_validation_errors or has_gap_issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
