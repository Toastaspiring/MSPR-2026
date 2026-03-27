with usine_a as (
    select
        cast(timestamp              as timestamp) as ts_event,
        part_id,
        id_lot_matiere,
        fournisseur,
        type_materiau,
        cast(longueur_brute_theo    as double) as longueur_brute_theo_mm,
        cast(longueur_brute_reelle  as double) as longueur_brute_reelle_mm,
        cast(vitesse_coupe          as double) as vitesse_coupe_mms,
        cast(temp_coupe             as double) as temp_coupe_c,
        upper(trim(etat_machine))              as etat_machine,
        cast(duree_cycle            as double) as duree_cycle_s,
        cast(taux_chute             as double) as taux_chute_pct,
        _source_usine,
        _source_file,
        _ingested_at
    from {{ source('raw_usine_a', 'm1_decoupe_matiere') }}
),

usine_b as (
    select
        cast(timestamp              as timestamp) as ts_event,
        part_id,
        id_lot_matiere,
        fournisseur,
        type_materiau,
        cast(longueur_brute_theo    as double) as longueur_brute_theo_mm,
        cast(longueur_brute_reelle  as double) as longueur_brute_reelle_mm,
        cast(vitesse_coupe          as double) as vitesse_coupe_mms,
        cast(temp_coupe             as double) as temp_coupe_c,
        upper(trim(etat_machine))              as etat_machine,
        cast(duree_cycle            as double) as duree_cycle_s,
        cast(taux_chute             as double) as taux_chute_pct,
        _source_usine,
        _source_file,
        _ingested_at
    from {{ source('raw_usine_b', 'm1_decoupe_matiere') }}
),

unioned as (
    select * from usine_a
    union all
    select * from usine_b
)

select * from unioned
where part_id  is not null
  and ts_event is not null
