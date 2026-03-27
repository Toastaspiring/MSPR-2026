-- Quality KPIs per plant per day
-- Primary source: M5_Contrôle_Qualité
-- Enriched with M6_Contrôle_Dimensionnel and M7_Contrôle_Visuel
with qualite as (
    select
        _source_usine                       as usine_id,
        cast(ts_event as date)              as date,
        part_id,
        is_conform,
        rebut_reason,
        final_angle_measure_deg
    from {{ ref('stg_m5_controle_qualite') }}
),

dimensionnel as (
    select
        _source_usine                       as usine_id,
        part_id,
        resultat                            as resultat_dim
    from {{ ref('stg_m6_controle_dimensionnel') }}
),

visuel as (
    select
        _source_usine                       as usine_id,
        part_id,
        decision                            as decision_vis,
        gravite_defaut
    from {{ ref('stg_m7_controle_visuel') }}
),

enriched as (
    select
        q.usine_id,
        q.date,
        q.part_id,
        q.is_conform,
        q.rebut_reason,
        d.resultat_dim,
        v.decision_vis,
        v.gravite_defaut
    from qualite q
    left join dimensionnel d using (usine_id, part_id)
    left join visuel       v using (usine_id, part_id)
),

aggregated as (
    select
        usine_id,
        date,

        count(*)                                                             as total_pieces,
        sum(case when is_conform     then 1 else 0 end)                      as pieces_conformes,
        sum(case when not is_conform then 1 else 0 end)                      as pieces_non_conformes,
        round(
            sum(case when is_conform then 1 else 0 end) * 100.0 / count(*),
        2)                                                                   as taux_conformite_pct,

        -- Rebut breakdown
        count(case when rebut_reason is not null then 1 end)                 as nb_rebuts,
        count(case when rebut_reason = 'Visual Defect' then 1 end)          as nb_rebuts_visuels,
        count(case when rebut_reason is not null
                    and rebut_reason != 'Visual Defect' then 1 end)         as nb_rebuts_autres,

        -- Dimensional control
        count(case when resultat_dim = 'NOK' then 1 end)                    as nb_nok_dimensionnel,

        -- Visual control
        count(case when decision_vis = 'RETOUCHE' then 1 end)               as nb_retouches,
        count(case when decision_vis = 'REBUT' then 1 end)                  as nb_rebuts_visuels_final,
        count(case when gravite_defaut = 'MAJEUR' then 1 end)               as nb_defauts_majeurs,
        count(case when gravite_defaut = 'MINEUR' then 1 end)               as nb_defauts_mineurs

    from enriched
    group by usine_id, date
)

select * from aggregated
order by usine_id, date
