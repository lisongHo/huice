from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from data.providers.tushare_readiness import collect_tushare_readiness, tushare_readiness_to_dict


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a small Tushare readiness preflight without triggering a full sync."
    )
    parser.add_argument("--config", type=Path, help="Optional provider config TOML path.")
    parser.add_argument(
        "--reference-date",
        help="Reference date in YYYY-MM-DD format. Defaults to today.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    report = collect_tushare_readiness(config_path=args.config, reference_date=args.reference_date)
    print(json.dumps(tushare_readiness_to_dict(report), indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
