# A-Share Minute Backtest Workbench Design

Date: 2026-03-28
Status: Final

## Summary

Build a single-user A-share minute-level backtesting workbench focused on research, not live trading.

Scope is intentionally narrow:

- China A-shares only
- Universe limited to symbols starting with `00`, `30`, or `60`
- Backtest window starts at `2022-01-01`
- Primary market data granularity is `1 minute`
- Primary strategy style is end-of-day and near-close execution
- Frontend is optimized for one researcher iterating quickly on ideas

This is not a broker-connected platform, not a multi-user system, and not a full tick-replay simulator.

The first implementation plan should target `v0.1` only. Later milestones remain part of the roadmap, but they are not required for the first build plan.

## Goals

### Product goals

- Let one user define a strategy, run backtests, inspect trades, and compare experiments quickly.
- Support minute-level research that is materially better than daily-bar approximation for near-close strategies.
- Preserve enough market structure to make A-share results believable: `T+1`, price limits, suspensions, taxes, fees, and listing status changes.
- Keep the system modular so the data provider can be swapped later without rewriting the backtest engine or UI.

### Research goals

- Support strategies such as:
  - consecutive down days
  - RSI threshold filters
  - buy near the close
  - hold for `N` trading days
  - sell near the close
- Support parameter scanning and run comparison.
- Support minute-level replay/diagnostics for selected trades.

## Non-goals

- Live trading or broker integration
- Full historical tick reconstruction
- Order book simulation, queue priority, or auction matching realism
- Multi-user permissions, sharing, or SaaS deployment
- Large-scale distributed compute in v0.1

## Design principles

- Single-user speed is more important than enterprise generality.
- A-share rule correctness is more important than generic framework elegance.
- Raw data should be stored once and transformed on demand.
- Runs must be reproducible: every backtest needs a saved config snapshot and result artifacts.
- Heavy computation must be explicit; UI changes should not auto-trigger long reruns.

## Recommended architecture

The system has five layers:

1. `data providers`
2. `data lake and metadata store`
3. `backtest core`
4. `reports and experiment registry`
5. `research workbench UI`

### 1. Data providers

Use a provider abstraction so upstream data can change later.

The provider interface should expose six domains:

- `MinuteBar`
- `TradeCalendar`
- `SecurityMaster`
- `AdjFactor/CorporateAction`
- `Suspension`
- `PriceLimit`

Internal symbol identity should be standardized in one format only. Adapters are responsible for mapping external styles such as `000001.SZ`, `000001.XSHE`, or plain `000001`.

### 2. Data lake and metadata store

Use:

- `Parquet` as the source-of-truth fact store
- `DuckDB` as the query, metadata, and experiment registry layer

Minute bars should be stored once in raw, unadjusted form. Do not persist separate full copies for raw, qfq, and hfq.

Corporate actions and adjustment factors should be stored separately and applied on demand in research views.

### 3. Backtest core

Implement a focused A-share minute backtest engine instead of forcing a generic framework to model A-share edge cases.

Core modules:

- `universe builder`
- `feature engine`
- `signal engine`
- `broker simulator`
- `portfolio ledger`
- `metrics engine`

### 4. Reports and experiment registry

Every run should produce:

- immutable `run_id`
- saved config snapshot
- summary metrics
- equity curve series
- drawdown series
- trade ledger
- optional diagnostic artifacts

### 5. Research workbench UI

Use `Streamlit` multi-page UI with `Plotly`.

This should behave like a research console, not a dashboard for presentation.

## Technology stack

- Python 3.12
- DuckDB
- Parquet
- Polars or Pandas for transforms
- Pydantic for config and schema validation
- Streamlit
- Plotly

Optional support libraries:

- `pandas-ta` or internal feature utilities for indicators
- `pyarrow` for Parquet handling

## Data design

### Storage rules

- Partition minute data by `trade_date=YYYY-MM-DD`
- Within each partition, sort by `symbol, bar_start_ts`
- Compress with `zstd`
- Prefer partition replacement over row-level mutation

Do not partition minute bars by symbol. That creates too many small files and hurts date-range backtests.

### Curated fact tables

#### Minute bars

Required fields:

- `symbol`
- `exchange`
- `trade_date`
- `bar_start_ts`
- `bar_end_ts`
- `open`
- `high`
- `low`
- `close`
- `volume`
- `amount`

Optional but valuable:

- `pre_close`
- `vwap`
- `is_synthetic_bar`

Time semantics for v0.1 are fixed as follows:

- all timestamps are interpreted in `Asia/Shanghai`
- `bar_start_ts` and `bar_end_ts` are full local datetimes, not wall-clock strings
- bars are labeled by start time
- a `14:57` bar means the interval `[14:57:00, 14:58:00)`
- `trade_date` is the exchange-local trading date associated with the bar
- the canonical deduplication key is `(symbol, bar_start_ts)`
- all provider adapters must normalize to this convention before data is published

#### Security master

Required fields:

- `symbol`
- `exchange`
- `list_date`
- `delist_date`
- `board`
- `name`
- `is_st`

`SecurityMaster` is only the latest static snapshot for convenience. It must not be used as the authoritative source for historical status-sensitive backtests.

#### Security status history

Required fields:

- `symbol`
- `effective_from`
- `effective_to`
- `name`
- `is_st`
- `status_reason`

This table is the authoritative dated history for:

- ST and non-ST transitions
- effective name changes
- any universe eligibility logic that depends on dated security status

#### Trading calendar

Required fields:

- `trade_date`
- `is_open`
- `prev_trade_date`
- `next_trade_date`

#### Corporate actions and adjustment factors

Required fields:

- `symbol`
- `ex_date`
- `adj_factor`
- `action_type`

#### Suspensions

Required fields:

- `symbol`
- `trade_date`
- `is_suspended`

#### Price limits

Required fields:

- `symbol`
- `trade_date`
- `pre_close`
- `up_limit`
- `down_limit`

### DuckDB metadata tables

DuckDB should hold only lightweight metadata and run tracking:

- `ingestion_runs`
- `file_manifest`
- `validation_results`
- `provider_capabilities`
- `backtest_runs`
- `backtest_run_tags`
- `scan_batches`

### Update workflow

Initial backfill:

- pull in smaller windows such as `single symbol + single month`
- normalize
- validate
- write partition
- update metadata

Daily refresh:

- fetch current trading day minute data after close
- refresh `trade_cal`, `stock_basic`, `adj_factor`, `suspension`, `price_limit`, `namechange`
- re-fetch a small correction window such as `T-1` to `T-3`

Weekly maintenance:

- gap scan
- partition replacement for defective days
- validation summary update

## Data quality checks

Minimum quality checks:

- no duplicate `(symbol, bar_start_ts)` keys
- no illegal OHLC relationships
- non-negative volume and amount
- minute count matches expected exchange session rules
- no minute bars outside valid session times
- security must exist and be live on that date
- suspended days must not look like normal trading days
- price limits must align with `pre_close`, board, and ST status
- adjustment factor jumps should only happen around real action dates

Business interpretation checks:

- distinguish true zero-volume bars from provider-filled synthetic bars
- compare minute aggregation to daily bars when available
- track coverage completeness by day and by symbol

## Backtest engine design

### Engine scope

The engine is minute-based, but optimized for strategy families that act near the close and hold over trading days.

It does not need to simulate every intraday microstructure detail in v0.1.

### Core execution flow

For each trade date:

1. load valid universe
2. load required minute slice and daily context
3. compute features
4. generate signals
5. simulate orders under A-share constraints
6. update positions and cash
7. persist run outputs

### Required A-share rules

The simulator must model:

- `T+1` for sell eligibility
- cash available same day after sell should follow standard stock account settlement assumptions used by the chosen broker model
- buy lot size of `100` shares; odd lots are only relevant on exit handling
- buy blocked at effective upper limit
- sell blocked at effective lower limit
- suspension means no execution
- commission
- transfer fee if applicable
- stamp duty on sells
- listing/delisting eligibility
- ST filtering support

Default market assumptions for v0.1:

- use standard continuous trading sessions and close handling
- default board limits are:
  - `00/60` main board: `10%`
  - `30` ChiNext: `20%`
- default ST handling is conservative: exclude `ST/*ST` from the tradable universe unless explicitly enabled
- exclude newly listed stocks for the first `5` trading days by default to avoid unlimited-price and unstable early-trading edge cases

### Tail-close execution modes

The system should support three execution modes:

#### `close_proxy`

Use the last available minute close near the session end.

Pros:

- simple
- fast

Cons:

- weakest realism

#### `last_5m_vwap`

Use a VWAP or weighted proxy from the last 5 minutes of continuous trading, then apply slippage.

Pros:

- best default for this platform
- more robust for near-close strategies

Cons:

- still not true auction modeling

#### `next_open_control`

Generate signal using prior day completed data and trade next session open.

Pros:

- strongest anti-lookahead control
- useful as a benchmark

Cons:

- not the same strategy semantics as near-close execution

Default recommendation: `last_5m_vwap`.

For v0.1, two timing modes are explicitly separated:

#### Default control mode

This is the default built-in strategy timing and the one used for acceptance testing.

1. compute daily features from the most recent completed daily bar set at the end of day `T-1`
2. decide candidate entries before the session of day `T`
3. submit near-close orders on day `T` at approximately `14:57`
4. confirm close participation or proxy execution at session end on day `T`
5. schedule sell eligibility based on `N` future trading days

#### Experimental same-day proxy mode

This mode is optional and must be clearly labeled experimental.

1. compute proxy features from intraday data available no later than the decision timestamp on day `T`
2. submit near-close orders on day `T`
3. confirm close participation or proxy execution at session end on day `T`

This mode must never read any full-day completed values from day `T`.

If close-auction-specific volume is available from the provider, execution should respect a configurable participation cap. If it is not available, the engine should fall back to a more conservative proxy such as last-minute or last-five-minute volume-aware execution plus extra slippage.

### Feature computation

The feature engine should support two classes of features:

- daily-context features such as consecutive down days and RSI
- intraday execution context such as last-five-minute VWAP

For near-close same-day signals, the platform must clearly distinguish:

- signals computed using only information available by the decision timestamp
- signals computed from completed daily bars and executed later

These must never be mixed silently.

Explicit v0.1 rule for the first built-in strategy template:

- daily features such as consecutive down days and RSI are computed from the most recent completed daily bar set at `T-1`
- the default production-safe template generates a signal from `T-1` data and executes near the close of day `T`
- a same-day near-close proxy mode may exist as an experimental option, but it must be labeled clearly and kept separate from the default control template

### Avoiding lookahead bias

Critical controls:

- do not use full-day closing data to justify same-day tail-close entry unless explicitly labeled as an approximation
- do not let future adjustment factors leak into historical signal generation
- do not apply future ST or suspension knowledge at earlier timestamps

### Parameter scanning

Parameter scans should not always replay all minute data from scratch.

Optimize by:

- caching candidate event days
- compressing the simulation to entry and exit decision events for strategy families that do not require full intraday replay
- separating feature generation from execution aggregation where possible
- reusing read-only market data slices
- writing scan results as grouped batches

## Strategy model

A strategy definition should include:

- metadata
- parameter schema
- universe filter
- feature requirements
- signal logic
- execution policy
- exit policy
- portfolio construction policy

The first built-in template should support:

- consecutive down-day threshold
- RSI threshold
- near-close buy
- hold for `N` trading days
- near-close sell

## Default v0.1 portfolio construction

To keep the first implementation plan concrete, the default portfolio policy is fixed as follows:

- initial capital: `1,000,000 CNY`
- allocation method: equal-weight across newly opened positions on each entry day
- max concurrent positions: `10`
- target position size floor: round down to the nearest board lot of `100` shares
- if more candidates fire than available slots, rank them by ascending RSI, then by larger consecutive-down count, then by symbol lexical order as a deterministic tie-breaker
- same symbol overlap is not allowed by default: if a symbol is already held, ignore new entry signals for that symbol
- cash from sells is reusable subject to the broker model assumptions encoded for v0.1; no margin and no shorting
- fractional leftover cash is left idle

## UI design

Use a multi-page Streamlit app with sidebar-based global controls and page-specific detail views.

### Pages

#### Home

Purpose:

- recent runs
- saved templates
- latest data health
- rerun last experiment quickly

#### Single backtest

Purpose:

- configure one run
- execute it explicitly
- inspect top-line results

Key controls:

- universe selector
- date range
- execution mode
- adjustment mode
- fees and slippage
- A-share rule toggles
- strategy parameters

Key outputs:

- summary metrics
- equity curve
- drawdown
- annual returns
- trade ledger

#### Parameter scan

Purpose:

- run grid or sampled searches
- compare parameter stability

Key outputs:

- heatmaps
- return vs drawdown scatter
- top result tables
- stability by year

#### Replay diagnostics

Purpose:

- inspect one run, one day, one symbol, or one trade

Key outputs:

- minute candles
- entry and exit markers
- indicator overlays
- volume
- position state
- MAE/MFE or similar trade diagnostics

#### Experiment library

Purpose:

- search and compare historical runs
- add tags and notes
- overlay multiple runs

### UI behavior rules

- heavy jobs only start on explicit button clicks
- result pages should prefer cached artifacts over recomputation
- complex tables and secondary charts should load lazily in tabs
- sidebar holds stable controls; advanced settings go into expanders

## Config and schema boundaries

Design these boundaries now so the system can evolve cleanly later:

- strategy config schema
- run submission schema
- result artifact schema
- chart data schema
- experiment registry schema

UI state must not be treated as the authoritative research configuration. Persisted run configs must be first-class objects.

## Suggested repository structure

```text
quantlab/
  app/
  data/
    providers/
    ingest/
    quality/
    store/
  backtest/
    core/
    models/
    metrics/
  strategies/
  reports/
  tests/
  scripts/
  configs/
```

## Codex implementation strategy

### Main agent responsibilities

The main Codex agent should:

- scaffold the repository
- define shared schemas and interfaces
- create the initial end-to-end smoke path
- coordinate integration

### Parallel sub-agent split

Use four workers with disjoint write scopes:

#### Worker 1: `data/**`

Owns:

- provider abstraction
- first provider adapter
- Parquet writes
- DuckDB metadata setup
- data validation

#### Worker 2: `backtest/**`

Owns:

- core simulation flow
- A-share constraints
- execution modes
- cost model
- portfolio ledger

#### Worker 3: `app/**`

Owns:

- Streamlit multi-page UI
- charts
- run selection and artifact browsing

#### Worker 4: `reports/**` and `tests/**`

Owns:

- metrics and summary outputs
- parameter scan result shaping
- smoke tests
- contract tests across run artifacts

### Integration order

1. main agent defines interfaces and schemas
2. workers build within their owned areas
3. main agent integrates a single sample strategy end to end
4. main agent resolves contract mismatches
5. run validation and smoke checks

## Milestones

### v0.1

- project scaffold
- one provider
- minute data storage and refresh
- one strategy template
- one backtest execution path
- single-backtest UI
- experiment persistence
- basic experiment browsing for previously completed runs
- default equal-weight portfolio construction with deterministic candidate selection

### v0.2

- parameter scan UI and storage
- replay diagnostics
- richer data quality summaries

### v0.3

- alternate provider adapter
- stronger caching and performance improvements
- more strategy templates

## Risks

- low-cost minute data may contain gaps or corrected values after the fact
- near-close execution is still approximate without auction microstructure
- minute-level scans can become slow if candidate-event caching is not built early
- adjustment and ST status leakage can silently bias results if data contracts are sloppy

## Acceptance criteria

The first implementation plan is successful when the `v0.1` system can:

- ingest and cache minute data for `2022-01-01` to present for symbols starting with `00`, `30`, or `60`
- run the first built-in near-close hold-for-`N`-days strategy using completed daily features from `T-1` and near-close execution on `T`
- report equity, drawdown, annual breakdown, and trade ledger
- persist runs and browse previously completed experiments
- switch execution mode between near-close approximation and next-open control for the same strategy family
- apply dated ST/name status history and the canonical minute-bar time convention consistently across ingest, backtest, and UI

Replay diagnostics and richer historical comparison remain planned for `v0.2+`, not required for the initial implementation plan.

## Open implementation choices

These choices are intentionally deferred to implementation planning:

- first paid or low-cost provider adapter
- exact indicator library vs fully internal indicator computation
- Polars vs Pandas as the main transform layer

They do not block planning because the required interface boundaries are already defined.
