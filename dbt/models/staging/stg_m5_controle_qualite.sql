with usine_a as (
    select
        cast(timestamp          as timestamp) as ts_event,
        part_id,
        -- 999.9 is a sentinel for sensor error (Usine_B observed, guard both)
        {{ clean_sentinel('cast(final_angle_measure as double)') }} as final_angle_measure_deg,
        cast(visual_score       as integer)  as visual_score,
        -- is_conform: 1/0 integer → boolean
        cast(is_conform         as integer) = 1 as is_conform,
        -- empty string → NULL
        nullif(trim(rebut_reason), '')       as rebut_reason,
        _source_usine,
        _source_file,
        _ingested_at
    from {{ source('raw_usine_a', 'm5_controle_qualite') }}
),

usine_b as (
    select
        cast(timestamp          as timestamp) as ts_event,
        part_id,
        {{ clean_sentinel('cast(final_angle_measure as double)') }} as final_angle_measure_deg,
        cast(visual_score       as integer)  as visual_score,
        cast(is_conform         as integer) = 1 as is_conform,
        nullif(trim(rebut_reason), '')       as rebut_reason,
        _source_usine,
        _source_file,
        _ingested_at
    from {{ source('raw_usine_b', 'm5_controle_qualite') }}
),

unioned as (
    select * from usine_a
    union all
    select * from usine_b
)

select * from unioned
where part_id  is not null
  and ts_event is not null
