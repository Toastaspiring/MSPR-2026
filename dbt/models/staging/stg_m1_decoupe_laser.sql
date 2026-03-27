with usine_a as (
    select
        cast(timestamp          as timestamp) as ts_event,
        part_id,
        cast(laser_power_kw     as double)    as laser_power_kw,
        cast(cutting_speed_mms  as double)    as cutting_speed_mms,
        cast(head_temp_c        as double)    as head_temp_c,
        cast(gas_consumption    as double)    as gas_consumption,
        upper(trim(status))                   as status,
        _source_usine,
        _source_file,
        _ingested_at
    from {{ source('raw_usine_a', 'm1_decoupe_laser') }}
),

usine_b as (
    select
        cast(timestamp          as timestamp) as ts_event,
        part_id,
        cast(laser_power_kw     as double)    as laser_power_kw,
        cast(cutting_speed_mms  as double)    as cutting_speed_mms,
        cast(head_temp_c        as double)    as head_temp_c,
        cast(gas_consumption    as double)    as gas_consumption,
        upper(trim(status))                   as status,
        _source_usine,
        _source_file,
        _ingested_at
    from {{ source('raw_usine_b', 'm1_decoupe_laser') }}
),

unioned as (
    select * from usine_a
    union all
    select * from usine_b
)

select * from unioned
where part_id  is not null
  and ts_event is not null
