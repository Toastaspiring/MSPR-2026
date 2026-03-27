with usine_a as (
    select
        cast(timestamp              as timestamp) as ts_event,
        part_id,
        cast(applied_pressure_bar   as double) as applied_pressure_bar,
        cast(target_angle           as double) as target_angle_deg,
        cast(actual_angle           as double) as actual_angle_deg,
        cast(hydraulic_temp_c       as double) as hydraulic_temp_c,
        -- derived: angular deviation
        round(abs(cast(actual_angle as double) - cast(target_angle as double)), 4) as angle_deviation_deg,
        _source_usine,
        _source_file,
        _ingested_at
    from {{ source('raw_usine_a', 'm3_presse_plieuse') }}
),

usine_b as (
    select
        cast(timestamp              as timestamp) as ts_event,
        part_id,
        cast(applied_pressure_bar   as double) as applied_pressure_bar,
        cast(target_angle           as double) as target_angle_deg,
        cast(actual_angle           as double) as actual_angle_deg,
        cast(hydraulic_temp_c       as double) as hydraulic_temp_c,
        round(abs(cast(actual_angle as double) - cast(target_angle as double)), 4) as angle_deviation_deg,
        _source_usine,
        _source_file,
        _ingested_at
    from {{ source('raw_usine_b', 'm3_presse_plieuse') }}
),

unioned as (
    select * from usine_a
    union all
    select * from usine_b
)

select * from unioned
where part_id  is not null
  and ts_event is not null
