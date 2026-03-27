-- Production actuelle vs objectif du plan, par usine et par jour.
-- Utilise un FULL OUTER JOIN pour conserver les jours sans plan (ex. dépassement nuit)
-- et les jours planifiés sans production (ex. arrêt inattendu).
with plan_daily as (
    select
        _source_usine                   as usine_id,
        date,
        sum(target_volume)              as target_volume_jour,
        count(distinct shift)           as nb_shifts_planifies
    from {{ ref('stg_production_plan') }}
    group by _source_usine, date
),

actual_daily as (
    select
        _source_usine                   as usine_id,
        cast(ts_event as date)          as date,
        count(distinct part_id)         as actual_volume
    from {{ ref('stg_m8_emballage') }}
    group by _source_usine, cast(ts_event as date)
),

joined as (
    select
        coalesce(p.usine_id,  a.usine_id)  as usine_id,
        coalesce(p.date,      a.date)       as date,
        p.target_volume_jour,
        p.nb_shifts_planifies,
        coalesce(a.actual_volume, 0)        as actual_volume
    from plan_daily   p
    full outer join actual_daily a using (usine_id, date)
)

select
    usine_id,
    date,
    coalesce(target_volume_jour, 0)                                                     as target_volume_jour,
    coalesce(nb_shifts_planifies, 0)                                                    as nb_shifts_planifies,
    actual_volume,
    actual_volume - coalesce(target_volume_jour, 0)                                     as ecart_volume,
    case
        when target_volume_jour is null or target_volume_jour = 0                       then null
        else round(actual_volume * 100.0 / target_volume_jour, 2)
    end                                                                                  as taux_realisation_pct,
    case
        when target_volume_jour is null or target_volume_jour = 0 then 'HORS_PLAN'
        when actual_volume >= target_volume_jour                   then 'ATTEINT'
        when actual_volume >= target_volume_jour * 0.9             then 'PROCHE'
        else 'EN_RETARD'
    end                                                                                  as statut_plan

from joined
order by usine_id, date
