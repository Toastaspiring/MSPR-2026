with usine_a as (
    select
        cast(timestamp          as timestamp) as ts_event,
        part_id,
        cast(punch_force_kn     as double)   as punch_force_kn,
        cast(vibration_level    as double)   as vibration_level,
        cast(motor_temp_c       as double)   as motor_temp_c,
        cast(cycle_count        as integer)  as cycle_count,
        upper(trim(status))                  as status,
        _source_usine,
        _source_file,
        _ingested_at
    from {{ source('raw_usine_a', 'm2_poinconneuse') }}
),

usine_b as (
    select
        cast(timestamp          as timestamp) as ts_event,
        part_id,
        cast(punch_force_kn     as double)   as punch_force_kn,
        cast(vibration_level    as double)   as vibration_level,
        cast(motor_temp_c       as double)   as motor_temp_c,
        cast(cycle_count        as integer)  as cycle_count,
        upper(trim(status))                  as status,
        _source_usine,
        _source_file,
        _ingested_at
    from {{ source('raw_usine_b', 'm2_poinconneuse') }}
),

unioned as (
    select * from usine_a
    union all
    select * from usine_b
)

select * from unioned
where part_id  is not null
  and ts_event is not null
