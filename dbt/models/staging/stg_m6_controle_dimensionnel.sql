with usine_a as (
    select
        cast(timestamp          as timestamp) as ts_event,
        part_id,
        -- id_piece dropped: always equals part_id (confirmed redundant)
        cast(dim_x              as double) as dim_x_mm,
        cast(dim_y              as double) as dim_y_mm,
        cast(dim_z              as double) as dim_z_mm,
        -- tol_min 999.9 = sentinel for missing tolerance (Usine_A observed)
        {{ clean_sentinel('cast(tol_min as double)') }} as tol_min_mm,
        cast(tol_max            as double) as tol_max_mm,
        cast(ecart_nominale     as double) as ecart_nominale_mm,
        upper(trim(resultat))             as resultat,
        -- 'NONE' = no defect, normalize to NULL
        nullif(upper(trim(type_defaut)), 'NONE') as type_defaut,
        id_operateur,
        _source_usine,
        _source_file,
        _ingested_at
    from {{ source('raw_usine_a', 'm6_controle_dimensionnel') }}
),

usine_b as (
    select
        cast(timestamp          as timestamp) as ts_event,
        part_id,
        cast(dim_x              as double) as dim_x_mm,
        cast(dim_y              as double) as dim_y_mm,
        cast(dim_z              as double) as dim_z_mm,
        {{ clean_sentinel('cast(tol_min as double)') }} as tol_min_mm,
        cast(tol_max            as double) as tol_max_mm,
        cast(ecart_nominale     as double) as ecart_nominale_mm,
        upper(trim(resultat))             as resultat,
        nullif(upper(trim(type_defaut)), 'NONE') as type_defaut,
        id_operateur,
        _source_usine,
        _source_file,
        _ingested_at
    from {{ source('raw_usine_b', 'm6_controle_dimensionnel') }}
),

unioned as (
    select * from usine_a
    union all
    select * from usine_b
)

select * from unioned
where part_id  is not null
  and ts_event is not null
