-- OEE proxy — source: M2 Usinage CNC (richest process telemetry)
-- OEE = Performance × Quality  (Availability approximated from etat_machine)
with cnc as (
    select
        _source_usine                                         as usine_id,
        id_machine,
        cast(ts_event as date)                                as date,
        etat_machine,
        nb_pieces_prod,
        nb_pieces_nok,
        temps_cycle_theo_s,
        temps_cycle_reel_s,
        puissance_conso_kw,
        usure_outil_pct,
        alarmes
    from {{ ref('stg_m2_usinage_cnc') }}
),

aggregated as (
    select
        usine_id,
        id_machine,
        date,
        count(*)                                                     as nb_enregistrements,

        -- Production
        sum(nb_pieces_prod)                                          as total_pieces_prod,
        sum(nb_pieces_nok)                                           as total_pieces_nok,
        sum(nb_pieces_prod) - sum(nb_pieces_nok)                     as total_pieces_ok,

        -- Quality rate
        round(
            (sum(nb_pieces_prod) - sum(nb_pieces_nok)) * 100.0
            / nullif(sum(nb_pieces_prod), 0),
        2)                                                           as taux_qualite_pct,

        -- Performance rate: theoretical / actual cycle time (>100% = faster than plan)
        round(
            avg(temps_cycle_theo_s / nullif(temps_cycle_reel_s, 0)) * 100,
        2)                                                           as taux_performance_pct,

        -- Availability proxy: fraction of records in RUN state
        round(
            sum(case when etat_machine = 'RUN' then 1 else 0 end) * 100.0
            / count(*),
        2)                                                           as taux_disponibilite_pct,

        -- OEE composite
        round(
            (sum(nb_pieces_prod) - sum(nb_pieces_nok)) * 100.0
            / nullif(sum(nb_pieces_prod), 0)
            * avg(temps_cycle_theo_s / nullif(temps_cycle_reel_s, 0))
            * sum(case when etat_machine = 'RUN' then 1 else 0 end) * 1.0 / count(*)
            / 100.0,
        2)                                                           as oee_pct,

        -- Health indicators
        round(avg(puissance_conso_kw), 2)                            as puissance_moy_kw,
        round(avg(usure_outil_pct), 2)                               as usure_outil_moy_pct,
        round(max(usure_outil_pct), 2)                               as usure_outil_max_pct,
        count(case when alarmes is not null then 1 end)              as nb_alarmes

    from cnc
    group by usine_id, id_machine, date
)

select * from aggregated
order by usine_id, id_machine, date
