with usine_a as (
    select
        cast(timestamp                  as timestamp) as ts_event,
        part_id,
        cast(couple_percage_nm          as double)  as couple_percage_nm,
        cast(vitesse_rotation_rpm       as integer) as vitesse_rotation_rpm,
        cast(nb_cycles_outil            as integer) as nb_cycles_outil,
        cast(usure_outil_pct            as double)  as usure_outil_pct,
        cast(temperature_actuateur      as double)  as temperature_actuateur_c,
        cast(micro_arrets               as integer) as micro_arrets,
        _source_usine,
        _source_file,
        _ingested_at
    from {{ source('raw_usine_a', 'm3_percage_taraudage') }}
),

usine_b as (
    select
        cast(timestamp                  as timestamp) as ts_event,
        part_id,
        cast(couple_percage_nm          as double)  as couple_percage_nm,
        cast(vitesse_rotation_rpm       as integer) as vitesse_rotation_rpm,
        cast(nb_cycles_outil            as integer) as nb_cycles_outil,
        cast(usure_outil_pct            as double)  as usure_outil_pct,
        cast(temperature_actuateur      as double)  as temperature_actuateur_c,
        cast(micro_arrets               as integer) as micro_arrets,
        _source_usine,
        _source_file,
        _ingested_at
    from {{ source('raw_usine_b', 'm3_percage_taraudage') }}
),

unioned as (
    select * from usine_a
    union all
    select * from usine_b
)

select * from unioned
where part_id  is not null
  and ts_event is not null
