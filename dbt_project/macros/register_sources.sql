-- macros/register_sources.sql
-- ─────────────────────────────────────────────────────────────────────────────
-- Called via on-run-start so that dbt source tests can resolve
-- `iceberg_raw.weather_events` inside DuckDB.
--
-- Creates a schema + view that reads Parquet files from MinIO (via httpfs)
-- matching the same glob pattern used in stg_weather.sql.
-- ─────────────────────────────────────────────────────────────────────────────

{% macro register_iceberg_sources() %}

  {% set bucket = env_var("MINIO_BUCKET", "lakehouse") %}

  {% set sql %}
    CREATE SCHEMA IF NOT EXISTS iceberg_raw;

    CREATE OR REPLACE VIEW iceberg_raw.weather_events AS
    SELECT *
    FROM read_parquet(
        's3://{{ bucket }}/warehouse/raw.db/weather_events/**/*.parquet',
        hive_partitioning = true,
        union_by_name     = true
    );
  {% endset %}

  {% do run_query(sql) %}
  {{ log("✅ Registered iceberg_raw.weather_events view", info=True) }}

{% endmacro %}
