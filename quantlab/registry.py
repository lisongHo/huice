from __future__ import annotations

from pathlib import Path

import duckdb


BOOTSTRAP_SQL = """
create table if not exists ingestion_runs (
    ingestion_run_id varchar primary key,
    provider_name varchar not null,
    started_at timestamp not null,
    finished_at timestamp,
    status varchar not null,
    notes varchar
);

create table if not exists file_manifest (
    dataset_name varchar not null,
    partition_key varchar not null,
    file_path varchar not null,
    row_count bigint,
    content_hash varchar,
    primary key (dataset_name, partition_key, file_path)
);

create table if not exists validation_results (
    validation_run_id varchar primary key,
    dataset_name varchar not null,
    check_name varchar not null,
    severity varchar not null,
    status varchar not null,
    details varchar
);

create table if not exists provider_capabilities (
    provider_name varchar primary key,
    supports_minute_bars boolean not null,
    supports_security_status_history boolean not null,
    supports_price_limits boolean not null,
    supports_suspensions boolean not null
);

create table if not exists backtest_runs (
    run_id varchar primary key,
    strategy_name varchar not null,
    start_date date not null,
    end_date date not null,
    execution_mode varchar not null,
    status varchar not null,
    created_at timestamp not null,
    completed_at timestamp,
    metrics_path varchar,
    artifacts_dir varchar not null
);

create table if not exists backtest_run_tags (
    run_id varchar not null,
    tag varchar not null
);

create table if not exists scan_batches (
    scan_batch_id varchar primary key,
    strategy_name varchar not null,
    created_at timestamp not null,
    result_path varchar not null
);

create table if not exists sync_runs (
    sync_run_id varchar primary key,
    workflow varchar not null,
    status varchar not null,
    requested_at timestamp not null,
    completed_at timestamp,
    summary_path varchar not null,
    artifact_dir varchar not null
);
"""


def bootstrap_registry(registry_path: Path) -> None:
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(registry_path)) as connection:
        connection.execute(BOOTSTRAP_SQL)
