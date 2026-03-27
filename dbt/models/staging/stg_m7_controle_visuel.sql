with usine_a as (
    select
        cast(timestamp          as timestamp) as ts_event,
        part_id,
        -- OUI/NON → boolean
        {{ normalize_oui_non('defaut_surface') }}   as defaut_surface,
        {{ normalize_oui_non('microfissure') }}      as microfissure,
        -- defaut_peinture can also be N/A → normalize returns NULL for N/A
        {{ normalize_oui_non('defaut_peinture') }}   as defaut_peinture,
        nullif(upper(trim(gravite_defaut)), '999.9')  as gravite_defaut,
        nullif(upper(trim(decision)), '999.9')       as decision,
        -- empty string → NULL
        nullif(trim(photo_url), '')                  as photo_url,
        _source_usine,
        _source_file,
        _ingested_at
    from {{ source('raw_usine_a', 'm7_controle_visuel') }}
),

usine_b as (
    select
        cast(timestamp          as timestamp) as ts_event,
        part_id,
        {{ normalize_oui_non('defaut_surface') }}   as defaut_surface,
        {{ normalize_oui_non('microfissure') }}      as microfissure,
        {{ normalize_oui_non('defaut_peinture') }}   as defaut_peinture,
        nullif(upper(trim(gravite_defaut)), '999.9')  as gravite_defaut,
        nullif(upper(trim(decision)), '999.9')       as decision,
        nullif(trim(photo_url), '')                  as photo_url,
        _source_usine,
        _source_file,
        _ingested_at
    from {{ source('raw_usine_b', 'm7_controle_visuel') }}
),

unioned as (
    select * from usine_a
    union all
    select * from usine_b
)

select * from unioned
where part_id  is not null
  and ts_event is not null
