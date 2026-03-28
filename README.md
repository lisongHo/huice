# Quantlab

Single-user A-share minute backtest workbench for local research.

## v0.1 scope

- backtest only, no live trading
- A-share universe limited to symbols starting with `00`, `30`, or `60`
- canonical minute bar semantics use `Asia/Shanghai`, `bar_start_ts`, `bar_end_ts`, and start-time labeling
- default built-in strategy uses `T-1` completed daily features and enters near the close on `T`
- default portfolio rules use `1,000,000` CNY, equal-weight sizing, max `10` positions, `100` share board lots, and no duplicate overlapping positions
- supported execution modes are `close_proxy`, `last_5m_vwap`, and `next_open_control`

## Status

The repository is being built directly from the v0.1 spec in `docs/superpowers/specs/2026-03-28-a-share-minute-backtest-workbench-design.md`.

## Quickstart

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m scripts.seed_demo_data
.venv/bin/python -m scripts.run_single_backtest
.venv/bin/streamlit run app/Home.py
```

The seeded demo flow is fully offline and writes local state under `.quantlab/`, including:

- parquet market data in `.quantlab/lake/`
- DuckDB registry in `.quantlab/registry.duckdb`
- persisted run artifacts in `.quantlab/runs/<run_id>/`

## Real Data Setup

This repository is usable without any provider credentials. The demo seed and local backtest scripts run entirely from local files.

When you connect a real upstream provider, keep its credentials out of git and treat them as provider-specific runtime inputs. In practice that usually means:

- a local config file ignored by git, or
- environment variables exported only in your shell/session

If those credentials are missing, the local seed and backtest flows should still work. Real-provider refresh/backfill jobs, once you add them, will require the provider's token or API key plus enough wall-clock time to fetch historical data.

## UI Pages

The Streamlit workbench currently ships with two pages:

- `Home` at `app/Home.py`: shows the template defaults, latest validation summary, recent runs, and workspace paths.
- `Single Backtest` at `app/pages/1_Single_Backtest.py`: prepares an explicit run request snapshot and browses persisted artifacts from completed runs.

The UI is intentionally request-driven. Changing widgets should prepare a draft; execution happens only from explicit script or button paths.

## v0.1 delivered

- local minute-bar ingestion into Parquet plus DuckDB metadata
- dated security status history support
- built-in T-1 daily-feature strategy with near-close and next-open control execution
- A-share rule handling for T+1, ST filter, suspension, price limits, fees, taxes, slippage, board lots, and no overlapping entries
- immutable run artifacts: config, metrics, equity, drawdown, trades, annual returns
- Streamlit multi-page workbench with recent runs and single-backtest result browsing
- local demo seed and single-run scripts that do not require provider credentials

## Deferred to v0.2+

- parameter scan UI
- replay diagnostics pages
- richer data quality dashboards
- alternate upstream provider adapters
