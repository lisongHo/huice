from __future__ import annotations

import argparse
import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from data.ingest.sync import json_dump, rebuild_dataset_partitions
from quantlab.config import AppPaths


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Rebuild local Parquet partitions from the currently stored dataset contents."
    )
    parser.add_argument(
        "--dataset",
        action="append",
        required=True,
        help="Dataset name to rebuild. Repeat for multiple datasets.",
    )
    parser.add_argument("--start-date", help="Optional inclusive start date filter.")
    parser.add_argument("--end-date", help="Optional inclusive end date filter.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Summarize the rebuild request without rewriting files.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    paths = AppPaths.from_workspace()
    datasets = tuple(dict.fromkeys(args.dataset))
    if args.dry_run:
        print(
            json_dump(
                {
                    "datasets": datasets,
                    "start_date": args.start_date,
                    "end_date": args.end_date,
                }
            )
        )
        return 0

    try:
        payload = [
            rebuild_dataset_partitions(
                paths=paths,
                dataset_name=dataset_name,
                start_date=args.start_date,
                end_date=args.end_date,
            )
            for dataset_name in datasets
        ]
    except Exception as exc:  # pragma: no cover - thin CLI wrapper
        print(str(exc), file=sys.stderr)
        return 1

    print(json_dump(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
