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


def test_bootstrap_registry_skips_existing_registry_without_reopening(monkeypatch, tmp_path: Path) -> None:
    registry_path = tmp_path / ".quantlab" / "registry.duckdb"
    bootstrap_registry(registry_path)

    def fail_connect(*args, **kwargs):
        raise AssertionError("bootstrap_registry should not reopen an existing registry file")

    monkeypatch.setattr(duckdb, "connect", fail_connect)

    bootstrap_registry(registry_path)
