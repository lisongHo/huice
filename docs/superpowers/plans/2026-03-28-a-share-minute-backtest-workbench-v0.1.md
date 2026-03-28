# A-Share Minute Backtest Workbench v0.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a single-user Python workbench that ingests A-share minute data, runs one built-in minute-level backtest with A-share constraints, persists immutable run artifacts, and displays completed runs in a Streamlit multi-page UI.

**Architecture:** The main agent owns repository scaffolding, shared Pydantic schemas, artifact contracts, and integration glue. Four disjoint workers implement `data/**`, `backtest/**`, `app/**`, and `reports/**` plus `tests/**` against those contracts, then the main agent stitches together a minimal end-to-end flow and verifies it with smoke tests.

**Tech Stack:** Python 3.12, DuckDB, Parquet, PyArrow, Pandas, Pydantic v2, Streamlit, Plotly, pytest

---

## File Map

- `pyproject.toml`: project metadata, dependencies, pytest config, streamlit entry points
- `README.md`: quickstart, v0.1 scope, demo workflow
- `quantlab/config.py`: app paths and environment-driven configuration
- `quantlab/schemas.py`: shared Pydantic schemas for run config, strategy params, execution modes, artifacts
- `quantlab/storage.py`: common path helpers for Parquet lake and run artifact layout
- `quantlab/registry.py`: DuckDB registry bootstrap and query helpers shared by all layers
- `quantlab/strategies/builtin.py`: built-in T-1 daily-feature strategy contract and ranking policy
- `data/**`: provider abstraction, local import provider, parquet publishing, metadata, validation
- `backtest/**`: broker simulation, A-share rules, execution modes, portfolio ledger, engine orchestration
- `reports/**`: metrics, annual breakdown, artifact persistence, scan result schema shell
- `app/**`: Streamlit home and single-backtest pages, result loading, charts
- `tests/**`: schema contracts, data validation, engine behavior, artifact persistence, smoke flow
- `scripts/run_single_backtest.py`: explicit CLI path to run one backtest end to end
- `scripts/seed_demo_data.py`: explicit helper to create/load a minimal local dataset for smoke verification

### Task 1: Bootstrap the repository and shared contracts

**Files:**
- Create: `pyproject.toml`
- Create: `README.md`
- Create: `quantlab/__init__.py`
- Create: `quantlab/config.py`
- Create: `quantlab/schemas.py`
- Create: `quantlab/storage.py`
- Create: `quantlab/registry.py`
- Create: `quantlab/strategies/__init__.py`
- Create: `quantlab/strategies/builtin.py`
- Test: `tests/test_schemas.py`

- [ ] **Step 1: Write the failing schema contract test**

```python
from quantlab.schemas import BacktestRunConfig, ExecutionMode

def test_backtest_run_config_defaults_match_v0_1():
    config = BacktestRunConfig.for_builtin_strategy(
        name="builtin_consecutive_down_rsi",
        start_date="2022-01-01",
        end_date="2022-01-10",
    )
    assert config.execution.mode == ExecutionMode.LAST_5M_VWAP
    assert config.portfolio.initial_cash == 1_000_000
    assert config.portfolio.max_positions == 10
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_schemas.py -v`
Expected: FAIL because package and schema do not exist yet.

- [ ] **Step 3: Implement minimal shared contracts**

Create the base package plus Pydantic models for:
- canonical symbol, trade date, and bar time semantics
- execution modes `close_proxy`, `last_5m_vwap`, `next_open_control`
- fixed default portfolio rules
- built-in strategy params using T-1 complete daily features and T-day tail-close execution
- run artifact references and immutable `run_id`

- [ ] **Step 4: Run tests to verify green**

Run: `pytest tests/test_schemas.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml README.md quantlab tests/test_schemas.py
git commit -m "feat: scaffold quantlab shared contracts"
```

### Task 2: Implement `data/**` for provider, parquet lake, metadata, and quality

**Files:**
- Create: `data/__init__.py`
- Create: `data/providers/__init__.py`
- Create: `data/providers/base.py`
- Create: `data/providers/local_bundle.py`
- Create: `data/ingest/__init__.py`
- Create: `data/ingest/publish.py`
- Create: `data/store/__init__.py`
- Create: `data/store/parquet_store.py`
- Create: `data/store/duckdb_registry.py`
- Create: `data/quality/__init__.py`
- Create: `data/quality/checks.py`
- Create: `tests/data/test_publish.py`
- Create: `tests/data/test_quality.py`

- [ ] **Step 1: Write failing tests for publishing and validation**

Add tests that assert:
- minute bars are normalized to `Asia/Shanghai`
- dedupe key is `(symbol, bar_start_ts)`
- partitions write to `trade_date=YYYY-MM-DD`
- validation catches duplicate keys and illegal OHLC
- dated security status history is stored and queryable

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/data/test_publish.py tests/data/test_quality.py -v`
Expected: FAIL because modules do not exist.

- [ ] **Step 3: Implement minimal data layer**

Build:
- provider protocols for minute bars, calendar, security master, status history, suspensions, price limits, adjustment factors
- first concrete provider as local bundle/import adapter for deterministic local data
- parquet writer with zstd compression and date partitions
- DuckDB metadata bootstrap for ingestion runs, file manifest, validation results, provider capabilities
- quality checks required by the spec

- [ ] **Step 4: Re-run tests**

Run: `pytest tests/data/test_publish.py tests/data/test_quality.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add data tests/data
git commit -m "feat: add data ingestion and validation layer"
```

### Task 3: Implement `backtest/**` for A-share execution and ledger

**Files:**
- Create: `backtest/__init__.py`
- Create: `backtest/models.py`
- Create: `backtest/core/__init__.py`
- Create: `backtest/core/engine.py`
- Create: `backtest/core/universe.py`
- Create: `backtest/core/features.py`
- Create: `backtest/core/execution.py`
- Create: `backtest/core/broker.py`
- Create: `backtest/core/ledger.py`
- Create: `backtest/metrics/__init__.py`
- Create: `tests/backtest/test_engine.py`
- Create: `tests/backtest/test_rules.py`

- [ ] **Step 1: Write failing backtest behavior tests**

Add tests that assert:
- built-in strategy uses T-1 completed daily bars only
- buy and sell obey board lot, T+1, suspension, price-limit, ST exclusion, and no duplicate overlapping positions
- execution modes produce deterministic fills
- same-day control mode never reads completed T-day bars

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/backtest/test_engine.py tests/backtest/test_rules.py -v`
Expected: FAIL because engine modules do not exist.

- [ ] **Step 3: Implement minimal engine**

Build:
- daily feature computation from minute-to-daily aggregation using T-1 complete data
- built-in consecutive-down + RSI ranking strategy
- order sizing and ranking under fixed portfolio defaults
- broker simulator with `close_proxy`, `last_5m_vwap`, `next_open_control`
- fee model with commission, transfer fee, sell stamp duty, and slippage
- equity and cash ledger persisted per trading day

- [ ] **Step 4: Re-run tests**

Run: `pytest tests/backtest/test_engine.py tests/backtest/test_rules.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backtest tests/backtest
git commit -m "feat: add a-share minute backtest engine"
```

### Task 4: Implement `reports/**` and `tests/**` for persisted artifacts

**Files:**
- Create: `reports/__init__.py`
- Create: `reports/artifacts.py`
- Create: `reports/metrics.py`
- Create: `reports/scans.py`
- Create: `tests/reports/test_artifacts.py`
- Create: `tests/test_smoke_pipeline.py`

- [ ] **Step 1: Write failing artifact tests**

Add tests that assert each run persists:
- `run_id`
- config snapshot
- summary metrics
- equity curve
- drawdown curve
- trade ledger
- annual returns table

Also assert the parameter-scan batch schema exists even if the UI is deferred.

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/reports/test_artifacts.py tests/test_smoke_pipeline.py -v`
Expected: FAIL because report modules do not exist.

- [ ] **Step 3: Implement minimal reporting layer**

Build:
- performance metric calculations
- annual breakdown output
- artifact writer/loader for run directories and DuckDB registry rows
- scan batch summary schema and persistence helpers without a full scan UI
- smoke pipeline fixture data for end-to-end validation

- [ ] **Step 4: Re-run tests**

Run: `pytest tests/reports/test_artifacts.py tests/test_smoke_pipeline.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add reports tests/reports tests/test_smoke_pipeline.py
git commit -m "feat: add backtest reporting artifacts"
```

### Task 5: Implement `app/**` for Streamlit multi-page workbench

**Files:**
- Create: `app/Home.py`
- Create: `app/pages/1_Single_Backtest.py`
- Create: `app/ui/__init__.py`
- Create: `app/ui/data_access.py`
- Create: `app/ui/charts.py`
- Create: `app/ui/forms.py`
- Create: `tests/app/test_app_data_access.py`

- [ ] **Step 1: Write failing UI data-access tests**

Add tests that assert:
- the home page loader reads recent runs and latest validation summaries from artifacts and registry
- single-backtest page constructs a persisted run submission payload but does not auto-run on widget change

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/app/test_app_data_access.py -v`
Expected: FAIL because app modules do not exist.

- [ ] **Step 3: Implement minimal Streamlit workbench**

Build:
- home page with recent runs, saved template defaults, latest data health
- single backtest page with explicit run button, strategy params, execution mode, fees/slippage, and date range
- Plotly charts for equity, drawdown, annual return, and trades table
- artifact-first loading so browsing completed runs does not recompute results

- [ ] **Step 4: Re-run tests**

Run: `pytest tests/app/test_app_data_access.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app tests/app
git commit -m "feat: add streamlit backtest workbench"
```

### Task 6: Integrate the minimal end-to-end flow

**Files:**
- Create: `scripts/run_single_backtest.py`
- Create: `scripts/seed_demo_data.py`
- Modify: `quantlab/registry.py`
- Modify: `README.md`
- Modify: `tests/test_smoke_pipeline.py`

- [ ] **Step 1: Write the failing end-to-end smoke test**

Add a test that:
- seeds a small local bundle dataset
- publishes data into the parquet lake and DuckDB registry
- runs the built-in strategy once
- persists run artifacts
- reads the result summary through app-facing loaders

- [ ] **Step 2: Run the smoke test to verify failure**

Run: `pytest tests/test_smoke_pipeline.py::test_end_to_end_single_run -v`
Expected: FAIL before integration glue exists.

- [ ] **Step 3: Implement minimal integration**

Wire together the seed/import flow, engine runner, artifact writer, and UI-facing readers. Ensure recomputation only happens via explicit script or button entry points.

- [ ] **Step 4: Run the smoke test and broader verification**

Run: `pytest -q`
Expected: PASS

Run: `python -m scripts.seed_demo_data`
Expected: writes local demo dataset and metadata

Run: `python -m scripts.run_single_backtest`
Expected: creates one persisted `run_id` with metrics, series, and trades

- [ ] **Step 5: Commit**

```bash
git add scripts README.md tests/test_smoke_pipeline.py quantlab/registry.py
git commit -m "feat: integrate minute backtest workbench v0.1"
```

## Notes

- `v0.2+` items stay out of scope except for structural placeholders: parameter scan UI, replay diagnostics UI, richer data quality dashboards, alternate providers.
- The first provider should be local-file friendly to keep the system deterministic and usable offline. Real upstream connectors can be added later without changing core contracts.
