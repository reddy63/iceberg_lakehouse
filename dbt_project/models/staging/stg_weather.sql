-- models/staging/stg_weather.sql
-- ─────────────────────────────────────────────────────────────────────────────
-- Reads raw Parquet files from the Iceberg warehouse on MinIO.
-- Casts types and extracts dates for weather data.
-- De-duplicates repeated scheduler fetches (same forecast hour fetched multiple times).
-- Materialised as a VIEW (cheap; no extra storage).
-- ─────────────────────────────────────────────────────────────────────────────

{{ config(materialized='view') }}

with raw as (

    select *
    from read_parquet(
        's3://{{ env_var("MINIO_BUCKET", "lakehouse") }}/warehouse/raw.db/weather_events/**/*.parquet',
        hive_partitioning = true,
        union_by_name     = true   -- tolerates schema evolution across files
    )

),

typed as (

    select
        -- Parse event_time: Open-Meteo returns 'YYYY-MM-DDTHH:MM' (no seconds).
        -- try_cast silently nulls that format, so strptime is the primary parse.
        -- The try_cast fallback handles files that already store a native timestamp.
        coalesce(
            strptime(try_cast(event_time as varchar), '%Y-%m-%dT%H:%M'),
            try_cast(event_time as timestamp)
        ) as event_ts,

        -- metrics
        try_cast(temperature_2m as double) as temperature_2m,
        try_cast(relative_humidity_2m as bigint) as relative_humidity_2m,
        try_cast(wind_speed_10m as double) as wind_speed_10m,
        try_cast(precipitation as double) as precipitation,
        try_cast(surface_pressure as double) as surface_pressure,

        -- metadata
        try_cast(weather_code as bigint) as weather_code,
        try_cast(latitude as double) as latitude,
        try_cast(longitude as double) as longitude,
        cast(timezone as varchar) as timezone,
        try_cast(fetched_at as timestamp) as fetched_at

    from raw
    where event_time is not null

),

deduped as (

    select
        *,
        -- Unique ID: hash of event_ts + location
        md5(cast(event_ts as varchar) || '|' || cast(latitude as varchar) || '|' || cast(longitude as varchar)) as event_id,
        -- Date extraction
        cast(date_trunc('day', event_ts) as date) as event_date
    from typed
    -- Keep only the latest fetch for each (event_ts, location) combination
    qualify row_number() over (
        partition by event_ts, latitude, longitude
        order by fetched_at desc
    ) = 1

)

select * from deduped
