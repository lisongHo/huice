from __future__ import annotations

from pathlib import Path

import duckdb

from quantlab.registry import bootstrap_registry


def test_bootstrap_registry_creates_schema_for_missing_file(tmp_path: Path) -> None:
    registry_path = tmp_path / ".quantlab" / "registry.duckdb"

    bootstrap_registry(registry_path)

    assert registry_path.exists()
    with duckdb.connect(str(registry_path), read_only=True) as connection:
        tables = {
            row[0]
            for row in connection.execute("show tables").fetchall()
        }

    assert "backtest_runs" in tables
    assert "validation_results" in tables
    assert "scan_batches" in tables
    assert "sync_runs" in tables


def test_bootstrap_registry_reopens_existing_registry_to_apply_missing_tables(tmp_path: Path) -> None:
    registry_path = tmp_path / ".quantlab" / "registry.duckdb"
    bootstrap_registry(registry_path)

    bootstrap_registry(registry_path)

    with duckdb.connect(str(registry_path), read_only=True) as connection:
        tables = {
            row[0]
            for row in connection.execute("show tables").fetchall()
        }

    assert "sync_runs" in tables
