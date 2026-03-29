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

The Home page now includes a readiness preflight that tells you whether real provider data is published, whether permissions are missing, and which next step to take. If the banner says the provider is not ready, seed demo data for offline exploration or finish the provider sync/backfill before expecting live-data results.

Before running a full sync, use the lightweight Tushare preflight:

```bash
.venv/bin/python -m scripts.tushare_preflight --reference-date 2026-03-28
```

It checks whether the local config is visible plus whether `trade_cal`, `stock_basic`, and `stk_mins` are accessible for the current token.

To persist the latest provider check for the UI and keep a timestamped readiness history, run:

```bash
.venv/bin/python -m scripts.tushare_preflight --reference-date 2026-03-28 --persist
```

## UI Pages

The Streamlit workbench currently ships with six pages:

- `Home` at `app/Home.py`: shows the readiness preflight, template defaults, latest validation summary, recent runs, scan batches, experiment-library entries, and workspace paths.
- `单次回测` at `app/pages/1_单次回测.py`: prepares one explicit run request and browses persisted artifacts from completed runs.
- `数据健康` at `app/pages/2_数据健康.py`: reads validation samples, file manifests, and provider capability rows from the registry.
- `参数扫描` at `app/pages/3_参数扫描.py`: prepares scan grids explicitly, checks for a scan runner hook, and browses persisted scan batches.
- `回放诊断` at `app/pages/4_回放诊断.py`: inspects saved run artifacts, equity curves, and trade-level diagnostics.
- `数据源就绪检查` at `app/pages/5_数据源就绪检查.py`: runs the readiness preflight only when you click the button and saves the latest result for later review.
- `同步驾驶舱` at `app/pages/6_同步驾驶舱.py`: prepares explicit sync requests, supports both dry-run planning and real execution on button click, shows the latest saved readiness snapshot first, and browses saved sync runs with actionable provider blocker guidance.

The UI is intentionally request-driven. Changing widgets should prepare a draft; execution happens only from explicit script or button paths.

## v0.1 delivered

- local minute-bar ingestion into Parquet plus DuckDB metadata
- dated security status history support
- built-in T-1 daily-feature strategy with near-close and next-open control execution
- A-share rule handling for T+1, ST filter, suspension, price limits, fees, taxes, slippage, board lots, and no overlapping entries
- immutable run artifacts: config, metrics, equity, drawdown, trades, annual returns
- Streamlit 多页面工作台，包含中文化的首页、单次回测、数据健康、参数扫描、回放诊断、数据源就绪检查和同步驾驶舱
- local demo seed and single-run scripts that do not require provider credentials
- readiness/preflight messaging for real-data setup, including persisted readiness history
- explicit sync planning and execution with persisted sync-run artifacts and actionable provider blocker diagnostics
