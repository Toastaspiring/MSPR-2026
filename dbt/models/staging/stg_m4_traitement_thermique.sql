with usine_a as (
    select
        cast(timestamp                  as timestamp) as ts_event,
        part_id,
        batch_id,
        -- lot_four dropped: identical to batch_id (confirmed redundant)
        cast(temp_four_c                as double)  as temp_four_c,
        -- courbe_montee_ok: OK/NOK → boolean
        case
            when upper(trim(courbe_montee_ok)) = 'OK'  then true
            when upper(trim(courbe_montee_ok)) = 'NOK' then false
            else null
        end                                         as courbe_montee_ok,
        cast(duree_palier_min           as double)  as duree_palier_min,
        cast(temps_refroidissement_min  as double)  as temps_refroidissement_min,
        -- durete_sortie_hrc can be NULL (sensor gap observed in Usine_B)
        cast(nullif(trim(cast(durete_sortie_hrc as varchar)), '') as double) as durete_sortie_hrc,
        _source_usine,
        _source_file,
        _ingested_at
    from {{ source('raw_usine_a', 'm4_traitement_thermique') }}
),

usine_b as (
    select
        cast(timestamp                  as timestamp) as ts_event,
        part_id,
        batch_id,
        cast(temp_four_c                as double)  as temp_four_c,
        case
            when upper(trim(courbe_montee_ok)) = 'OK'  then true
            when upper(trim(courbe_montee_ok)) = 'NOK' then false
            else null
        end                                         as courbe_montee_ok,
        cast(duree_palier_min           as double)  as duree_palier_min,
        cast(temps_refroidissement_min  as double)  as temps_refroidissement_min,
        cast(nullif(trim(cast(durete_sortie_hrc as varchar)), '') as double) as durete_sortie_hrc,
        _source_usine,
        _source_file,
        _ingested_at
    from {{ source('raw_usine_b', 'm4_traitement_thermique') }}
),

unioned as (
    select * from usine_a
    union all
    select * from usine_b
)

select * from unioned
where part_id  is not null
  and ts_event is not null
