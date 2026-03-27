with usine_a as (
    select
        cast(date       as date)        as date,
        shift,
        cast(start_time as time)        as start_time,
        cast(end_time   as time)        as end_time,
        cast(target_volume as integer)  as target_volume,
        _source_usine,
        _source_file,
        _ingested_at
    from {{ source('raw_usine_a', 'production_plan') }}
),

usine_b as (
    select
        cast(date       as date)        as date,
        shift,
        cast(start_time as time)        as start_time,
        cast(end_time   as time)        as end_time,
        cast(target_volume as integer)  as target_volume,
        _source_usine,
        _source_file,
        _ingested_at
    from {{ source('raw_usine_b', 'production_plan') }}
),

unioned as (
    select * from usine_a
    union all
    select * from usine_b
)

select * from unioned
where date is not null
