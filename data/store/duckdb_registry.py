from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import duckdb

from data.providers.base import ProviderCapabilities
from data.quality.checks import QualityCheckResult
from data.store.parquet_store import WrittenFile
from quantlab.registry import bootstrap_registry


def start_ingestion_run(registry_path: Path, provider_name: str, notes: str | None = None) -> str:
    bootstrap_registry(registry_path)
    ingestion_run_id = uuid4().hex
    with duckdb.connect(str(registry_path)) as connection:
        connection.execute(
            """
            insert into ingestion_runs (
                ingestion_run_id,
                provider_name,
                started_at,
                finished_at,
                status,
                notes
            ) values (?, ?, ?, ?, ?, ?)
            """,
            [
                ingestion_run_id,
                provider_name,
                datetime.now(UTC),
                None,
                "running",
                notes,
            ],
        )
    return ingestion_run_id


def finish_ingestion_run(registry_path: Path, ingestion_run_id: str, status: str) -> None:
    bootstrap_registry(registry_path)
    with duckdb.connect(str(registry_path)) as connection:
        connection.execute(
            """
            update ingestion_runs
            set finished_at = ?, status = ?
            where ingestion_run_id = ?
            """,
            [datetime.now(UTC), status, ingestion_run_id],
        )


def record_file_manifest(registry_path: Path, files: list[WrittenFile]) -> None:
    if not files:
        return

    bootstrap_registry(registry_path)
    with duckdb.connect(str(registry_path)) as connection:
        for written_file in files:
            connection.execute(
                """
                insert into file_manifest (
                    dataset_name,
                    partition_key,
                    file_path,
                    row_count,
                    content_hash
                ) values (?, ?, ?, ?, ?)
                on conflict (dataset_name, partition_key, file_path) do update set
                    row_count = excluded.row_count,
                    content_hash = excluded.content_hash
                """,
                [
                    written_file.dataset_name,
                    written_file.partition_key,
                    written_file.file_path,
                    written_file.row_count,
                    written_file.content_hash,
                ],
            )


def record_validation_results(registry_path: Path, results: list[QualityCheckResult]) -> None:
    if not results:
        return

    bootstrap_registry(registry_path)
    with duckdb.connect(str(registry_path)) as connection:
        for result in results:
            connection.execute(
                """
                insert into validation_results (
                    validation_run_id,
                    dataset_name,
                    check_name,
                    severity,
                    status,
                    details
                ) values (?, ?, ?, ?, ?, ?)
                """,
                [
                    result.validation_run_id,
                    result.dataset_name,
                    result.check_name,
                    result.severity,
                    result.status,
                    result.details,
                ],
            )


def record_provider_capabilities(
    registry_path: Path,
    provider_name: str,
    capabilities: ProviderCapabilities,
) -> None:
    bootstrap_registry(registry_path)
    with duckdb.connect(str(registry_path)) as connection:
        connection.execute(
            """
            insert into provider_capabilities (
                provider_name,
                supports_minute_bars,
                supports_security_status_history,
                supports_price_limits,
                supports_suspensions
            ) values (?, ?, ?, ?, ?)
            on conflict (provider_name) do update set
                supports_minute_bars = excluded.supports_minute_bars,
                supports_security_status_history = excluded.supports_security_status_history,
                supports_price_limits = excluded.supports_price_limits,
                supports_suspensions = excluded.supports_suspensions
            """,
            [
                provider_name,
                capabilities.supports_minute_bars,
                capabilities.supports_security_status_history,
                capabilities.supports_price_limits,
                capabilities.supports_suspensions,
            ],
        )
