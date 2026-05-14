-- models/marts/fct_weather_daily.sql
-- ─────────────────────────────────────────────────────────────────────────────
-- Business-level fact table: daily aggregations for weather data.
-- Materialised as a TABLE for fast dashboard queries.
-- ─────────────────────────────────────────────────────────────────────────────

{{ config(materialized='table') }}

with base as (

    select * from {{ ref('stg_weather') }}

),

aggregated as (

    select
        event_date,
        latitude,
        longitude,

        -- temperature
        max(temperature_2m) as max_temperature_2m,
        min(temperature_2m) as min_temperature_2m,
        avg(temperature_2m) as avg_temperature_2m,

        -- other metrics
        avg(relative_humidity_2m) as avg_humidity,
        max(wind_speed_10m) as max_wind_speed,
        sum(precipitation) as total_precipitation,
        avg(surface_pressure) as avg_surface_pressure,

        -- count of hourly records
        count(*) as hourly_records,

        -- audit
        max(fetched_at) as last_fetched_at

    from base
    group by 1, 2, 3

)

select * from aggregated
order by event_date desc
