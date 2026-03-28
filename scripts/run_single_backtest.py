from __future__ import annotations

import json

from backtest.core.engine import run_backtest
from quantlab.config import AppPaths
from quantlab.strategies.builtin import default_strategy_config
from reports.artifacts import persist_backtest_result
from scripts.seed_demo_data import seed_demo_data


def run_single_backtest() -> str:
    paths = AppPaths.from_workspace()
    seed_demo_data(paths)
    config = default_strategy_config(start_date="2022-01-03", end_date="2022-01-10")
    result = run_backtest(paths, config)
    manifest = persist_backtest_result(paths, result)
    return json.dumps(manifest.model_dump(mode="json"), indent=2)


def main() -> None:
    print(run_single_backtest())


if __name__ == "__main__":
    main()
