from __future__ import annotations

import argparse
import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from data.ingest.sync import json_dump, run_backfill, sync_plan_to_dict, sync_run_summary_to_dict
from data.providers.tushare_provider import TushareConfigurationError, TushareRequestError
from data.providers.tushare_readiness import classify_tushare_planning_blocker, format_tushare_planning_blocker
from quantlab.config import AppPaths


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Backfill A-share minute data from Tushare Pro into the local Parquet/DuckDB lake."
    )
    parser.add_argument("--start-date", required=True, help="Inclusive start date in YYYY-MM-DD format.")
    parser.add_argument("--end-date", required=True, help="Inclusive end date in YYYY-MM-DD format.")
    parser.add_argument("--config", type=Path, help="Optional provider config TOML path.")
    parser.add_argument(
        "--symbols",
        nargs="*",
        help="Optional explicit symbol list. Symbols are restricted to 00/30/60 prefixes.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Plan the backfill without calling Tushare or writing data.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    paths = AppPaths.from_workspace()
    try:
        result = run_backfill(
            paths=paths,
            start_date=args.start_date,
            end_date=args.end_date,
            config_path=args.config,
            symbols=args.symbols,
            dry_run=args.dry_run,
        )
    except (TushareConfigurationError, TushareRequestError) as exc:
        blocker = classify_tushare_planning_blocker(exc)
        if blocker is not None:
            print(
                format_tushare_planning_blocker(blocker, workflow="Backfill", dry_run=args.dry_run),
                file=sys.stderr,
            )
            return 2
        print(str(exc), file=sys.stderr)
        return 2 if isinstance(exc, TushareConfigurationError) else 1
    except Exception as exc:  # pragma: no cover - thin CLI wrapper
        print(str(exc), file=sys.stderr)
        return 1

    payload = sync_plan_to_dict(result) if args.dry_run else sync_run_summary_to_dict(result)
    print(json_dump(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
