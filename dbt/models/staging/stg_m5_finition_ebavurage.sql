with usine_a as (
    select
        cast(timestamp                      as timestamp) as ts_event,
        part_id,
        cast(temps_cycle_sec                as double)  as temps_cycle_sec,
        cast(pression_outil_bar             as double)  as pression_outil_bar,
        cast(vitesse_rotation_outil_rpm     as integer) as vitesse_rotation_outil_rpm,
        -- OUI/NON → boolean
        {{ normalize_oui_non('taux_reprise_manuelle') }} as reprise_manuelle,
        cast(defauts_surface_detectes       as integer) as defauts_surface_detectes,
        _source_usine,
        _source_file,
        _ingested_at
    from {{ source('raw_usine_a', 'm5_finition_ebavurage') }}
),

usine_b as (
    select
        cast(timestamp                      as timestamp) as ts_event,
        part_id,
        cast(temps_cycle_sec                as double)  as temps_cycle_sec,
        cast(pression_outil_bar             as double)  as pression_outil_bar,
        cast(vitesse_rotation_outil_rpm     as integer) as vitesse_rotation_outil_rpm,
        {{ normalize_oui_non('taux_reprise_manuelle') }} as reprise_manuelle,
        cast(defauts_surface_detectes       as integer) as defauts_surface_detectes,
        _source_usine,
        _source_file,
        _ingested_at
    from {{ source('raw_usine_b', 'm5_finition_ebavurage') }}
),

unioned as (
    select * from usine_a
    union all
    select * from usine_b
)

select * from unioned
where part_id  is not null
  and ts_event is not null
