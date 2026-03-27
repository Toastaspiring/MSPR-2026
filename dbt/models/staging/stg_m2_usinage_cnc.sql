with usine_a as (
    select
        cast(timestamp              as timestamp) as ts_event,
        part_id,
        cast(vitesse_broche_rpm     as integer) as vitesse_broche_rpm,
        cast(avance_outil           as double)  as avance_outil_mm_min,
        cast(profondeur_passe       as double)  as profondeur_passe_mm,
        cast(temp_broche            as double)  as temp_broche_c,
        cast(temp_piece             as double)  as temp_piece_c,
        cast(vibration_broche       as double)  as vibration_broche,
        cast(couple_moteur          as double)  as couple_moteur_nm,
        cast(puissance_conso_kw     as double)  as puissance_conso_kw,
        cast(temps_cycle_theo       as double)  as temps_cycle_theo_s,
        cast(temps_cycle_reel       as double)  as temps_cycle_reel_s,
        cast(nb_pieces_prod         as integer) as nb_pieces_prod,
        cast(nb_pieces_nok          as integer) as nb_pieces_nok,
        id_machine,
        version_prog,
        cast(num_outil              as integer) as num_outil,
        cast(usure_outil_pct        as double)  as usure_outil_pct,
        upper(trim(etat_machine))               as etat_machine,
        -- 'NONE' is a sentinel for no alarm
        case when upper(trim(alarmes)) = 'NONE' then null else trim(alarmes) end as alarmes,
        _source_usine,
        _source_file,
        _ingested_at
    from {{ source('raw_usine_a', 'm2_usinage_cnc') }}
),

usine_b as (
    select
        cast(timestamp              as timestamp) as ts_event,
        part_id,
        cast(vitesse_broche_rpm     as integer) as vitesse_broche_rpm,
        cast(avance_outil           as double)  as avance_outil_mm_min,
        cast(profondeur_passe       as double)  as profondeur_passe_mm,
        cast(temp_broche            as double)  as temp_broche_c,
        cast(temp_piece             as double)  as temp_piece_c,
        cast(vibration_broche       as double)  as vibration_broche,
        cast(couple_moteur          as double)  as couple_moteur_nm,
        cast(puissance_conso_kw     as double)  as puissance_conso_kw,
        cast(temps_cycle_theo       as double)  as temps_cycle_theo_s,
        cast(temps_cycle_reel       as double)  as temps_cycle_reel_s,
        cast(nb_pieces_prod         as integer) as nb_pieces_prod,
        cast(nb_pieces_nok          as integer) as nb_pieces_nok,
        id_machine,
        version_prog,
        cast(num_outil              as integer) as num_outil,
        cast(usure_outil_pct        as double)  as usure_outil_pct,
        upper(trim(etat_machine))               as etat_machine,
        case when upper(trim(alarmes)) = 'NONE' then null else trim(alarmes) end as alarmes,
        _source_usine,
        _source_file,
        _ingested_at
    from {{ source('raw_usine_b', 'm2_usinage_cnc') }}
),

unioned as (
    select * from usine_a
    union all
    select * from usine_b
)

select * from unioned
where part_id  is not null
  and ts_event is not null
