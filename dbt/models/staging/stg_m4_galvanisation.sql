-- NOTE: Galvanisation operates at BATCH granularity — no part_id.
-- Join to stg_m4_traitement_thermique via batch_id to link back to parts.
with usine_a as (
    select
        cast(timestamp              as timestamp) as ts_event,
        batch_id,
        cast(oven_temp_c            as double) as oven_temp_c,
        cast(immersion_time_sec     as double) as immersion_time_sec,
        cast(coating_thickness_um   as double) as coating_thickness_um,
        cast(energy_kwh             as double) as energy_kwh,
        _source_usine,
        _source_file,
        _ingested_at
    from {{ source('raw_usine_a', 'm4_galvanisation') }}
),

usine_b as (
    select
        cast(timestamp              as timestamp) as ts_event,
        batch_id,
        cast(oven_temp_c            as double) as oven_temp_c,
        cast(immersion_time_sec     as double) as immersion_time_sec,
        cast(coating_thickness_um   as double) as coating_thickness_um,
        cast(energy_kwh             as double) as energy_kwh,
        _source_usine,
        _source_file,
        _ingested_at
    from {{ source('raw_usine_b', 'm4_galvanisation') }}
),

unioned as (
    select * from usine_a
    union all
    select * from usine_b
)

select * from unioned
where batch_id is not null
  and ts_event is not null
