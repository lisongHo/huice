# A-Share Workbench Expanded Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand the current local A-share minute backtest workbench into a research-ready local application with real-data ingestion hooks, explicit run execution from the UI, richer data health and experiment browsing, and the first v0.2 pages.

**Architecture:** Keep the current local single-user Python architecture, but add a production-oriented data sync layer and explicit orchestration scripts on top of the existing Parquet + DuckDB + Streamlit stack. Work is split across disjoint scopes so workers can proceed in parallel: data sync/providers, UI execution and new pages, reports/health/scan/replay artifacts, and engineering hardening plus Git wiring.

**Tech Stack:** Python 3.12+, DuckDB, Parquet, PyArrow, Pandas, Pydantic v2, Streamlit, Plotly, pytest, Git

---

## Scope Notes

- The GitHub repository `https://github.com/lisongHo/huice` is currently empty. The current workspace will become that repository’s initial content.
- “Real offline data” is split into two parts:
  - implementation: provider(s), bulk import scripts, manifesting, refresh flow, quality checks
  - actual historical sync execution: depends on provider credentials, provider rate limits, and wall-clock runtime
- If a credentialed provider is required, implement the integration and configuration even if the full backfill cannot be completed in-session.

## File Map

- `configs/`: provider config templates, scan configs, reusable run configs
- `scripts/sync_*`: real data import, refresh, validation, backfill, and maintenance commands
- `data/providers/`: add at least one non-demo provider and improve local import contracts
- `data/ingest/`: batch sync orchestration, correction windows, maintenance scans
- `data/quality/`: stronger validation summaries and repair-oriented reports
- `backtest/`: keep current core, add parameter scan orchestration and replay-support outputs
- `reports/`: scan batches, replay-support artifacts, richer summaries
- `app/`: explicit run execution, parameter scan page, replay diagnostics page, data health page, experiment library improvements
- `tests/`: coverage for sync scripts, health summaries, scan/replay storage, UI execution flow

### Task 1: Git bootstrap and repo hardening

**Files:**
- Modify: `.gitignore`
- Modify: `README.md`
- Create: `configs/provider.example.toml`
- Create: `configs/scan.example.json`
- Create: `docs/superpowers/plans/2026-03-28-a-share-workbench-expanded-plan.md`

- [ ] Write failing documentation/config tests or smoke assertions for required config files.
- [ ] Add provider and scan config templates plus README guidance.
- [ ] Ensure local workspace is attached to the GitHub repo on `main`.
- [ ] Re-run smoke checks.

### Task 2: Real data sync and maintenance scripts

**Files:**
- Create/Modify under: `data/providers/**`, `data/ingest/**`, `scripts/sync_*.py`, `scripts/validate_data.py`, `scripts/rebuild_partitions.py`
- Test: `tests/data/test_sync_scripts.py`, `tests/data/test_provider_contracts.py`

- [ ] Add at least one real provider integration suitable for local historical import.
- [ ] Add explicit scripts for initial backfill, daily refresh, weekly maintenance, and gap scan.
- [ ] Add manifesting and correction-window re-fetch support.
- [ ] Add tests for provider contract normalization and sync script wiring.

### Task 3: Explicit UI execution and experiment library upgrades

**Files:**
- Modify/Create under: `app/**`
- Test: `tests/app/test_run_execution.py`, `tests/app/test_experiment_library.py`

- [ ] Wire the Single Backtest page to execute a run explicitly from the UI.
- [ ] Expand Home and experiment browsing.
- [ ] Add a dedicated data health page.
- [ ] Keep all heavy work behind explicit buttons.

### Task 4: v0.2 pages and richer artifacts

**Files:**
- Modify/Create under: `app/**`, `reports/**`, `backtest/**`
- Test: `tests/reports/test_scan_artifacts.py`, `tests/reports/test_replay_artifacts.py`

- [ ] Add a parameter scan page with persisted scan batches and comparison charts.
- [ ] Add replay diagnostics page backed by saved artifacts.
- [ ] Extend reports to persist scan and replay-support structures without recomputation by default.

### Task 5: Hardening, edge cases, and acceptance

**Files:**
- Modify/Create across: `scripts/**`, `tests/**`, `README.md`
- Test: `tests/test_end_to_end_realistic_flow.py`

- [ ] Add protections for duplicate run IDs, broken partitions, missing columns, and partial artifacts.
- [ ] Add edge-case tests for ST, suspension, price limits, T+1, listing-age filter, and maintenance scripts.
- [ ] Verify seed-demo flow and real-data-ready flow both work.
- [ ] Document what still requires credentials or long-running backfills.
