-- Full part traceability: one row per part, covering the entire production flow M1→M8.
-- M4_Galvanisation is joined via batch_id (no part_id at galvanisation stage).
with base as (
    -- Anchor on quality control — every finished part should appear here
    select distinct part_id, _source_usine as usine_id
    from {{ ref('stg_m5_controle_qualite') }}
),

laser       as (select part_id, _source_usine as usine_id, ts_event as ts_decoupe_laser,   status as status_laser         from {{ ref('stg_m1_decoupe_laser') }}),
matiere     as (select part_id, _source_usine as usine_id, type_materiau, fournisseur, id_lot_matiere, taux_chute_pct       from {{ ref('stg_m1_decoupe_matiere') }}),
poinc       as (select part_id, _source_usine as usine_id, ts_event as ts_poinconneuse,    punch_force_kn                  from {{ ref('stg_m2_poinconneuse') }}),
cnc         as (select part_id, _source_usine as usine_id, ts_event as ts_cnc,             temps_cycle_reel_s, nb_pieces_nok, usure_outil_pct as usure_cnc_pct, alarmes from {{ ref('stg_m2_usinage_cnc') }}),
percage     as (select part_id, _source_usine as usine_id, ts_event as ts_percage,         couple_percage_nm, micro_arrets  from {{ ref('stg_m3_percage_taraudage') }}),
presse      as (select part_id, _source_usine as usine_id, ts_event as ts_presse,          actual_angle_deg, angle_deviation_deg from {{ ref('stg_m3_presse_plieuse') }}),
thermique   as (select part_id, _source_usine as usine_id, batch_id, ts_event as ts_thermique, temp_four_c, durete_sortie_hrc, courbe_montee_ok from {{ ref('stg_m4_traitement_thermique') }}),
galva       as (select batch_id, _source_usine as usine_id, coating_thickness_um, energy_kwh as galva_energy_kwh from {{ ref('stg_m4_galvanisation') }}),
qualite     as (select part_id, _source_usine as usine_id, ts_event as ts_qualite,         is_conform, final_angle_measure_deg, visual_score, rebut_reason from {{ ref('stg_m5_controle_qualite') }}),
ebavurage   as (select part_id, _source_usine as usine_id, reprise_manuelle, defauts_surface_detectes from {{ ref('stg_m5_finition_ebavurage') }}),
dim         as (select part_id, _source_usine as usine_id, dim_x_mm, dim_y_mm, dim_z_mm, ecart_nominale_mm, resultat as resultat_dim from {{ ref('stg_m6_controle_dimensionnel') }}),
visuel      as (select part_id, _source_usine as usine_id, ts_event as ts_visuel,          decision as decision_vis, gravite_defaut, photo_url from {{ ref('stg_m7_controle_visuel') }}),
emballage   as (select part_id, _source_usine as usine_id, ts_event as ts_emballage,       client, date_expedition, num_lot_prod, certificat_conf from {{ ref('stg_m8_emballage') }})

select
    base.part_id,
    base.usine_id,

    -- M1 — Matière
    matiere.type_materiau,
    matiere.fournisseur,
    matiere.id_lot_matiere,
    matiere.taux_chute_pct,

    -- M1 — Laser
    laser.ts_decoupe_laser,
    laser.status_laser,

    -- M2 — Poinçonneuse
    poinc.ts_poinconneuse,
    poinc.punch_force_kn,

    -- M2 — CNC
    cnc.ts_cnc,
    cnc.temps_cycle_reel_s,
    cnc.nb_pieces_nok   as cnc_pieces_nok,
    cnc.usure_cnc_pct,
    cnc.alarmes         as cnc_alarmes,

    -- M3 — Perçage
    percage.ts_percage,
    percage.couple_percage_nm,
    percage.micro_arrets,

    -- M3 — Presse
    presse.ts_presse,
    presse.actual_angle_deg,
    presse.angle_deviation_deg,

    -- M4 — Thermique
    thermique.ts_thermique,
    thermique.batch_id,
    thermique.temp_four_c,
    thermique.durete_sortie_hrc,
    thermique.courbe_montee_ok,

    -- M4 — Galvanisation (via batch_id)
    galva.coating_thickness_um,
    galva.galva_energy_kwh,

    -- M5 — Ébavurage
    ebavurage.reprise_manuelle,
    ebavurage.defauts_surface_detectes,

    -- M5 — Qualité
    qualite.ts_qualite,
    qualite.is_conform,
    qualite.final_angle_measure_deg,
    qualite.visual_score,
    qualite.rebut_reason,

    -- M6 — Dimensionnel
    dim.dim_x_mm,
    dim.dim_y_mm,
    dim.dim_z_mm,
    dim.ecart_nominale_mm,
    dim.resultat_dim,

    -- M7 — Visuel
    visuel.ts_visuel,
    visuel.decision_vis,
    visuel.gravite_defaut,
    visuel.photo_url,

    -- M8 — Emballage
    emballage.ts_emballage,
    emballage.client,
    emballage.date_expedition,
    emballage.num_lot_prod,
    emballage.certificat_conf

from base
left join matiere   using (part_id, usine_id)
left join laser     using (part_id, usine_id)
left join poinc     using (part_id, usine_id)
left join cnc       using (part_id, usine_id)
left join percage   using (part_id, usine_id)
left join presse    using (part_id, usine_id)
left join thermique using (part_id, usine_id)
left join galva     on galva.batch_id = thermique.batch_id
                   and galva.usine_id = base.usine_id
left join qualite   using (part_id, usine_id)
left join ebavurage using (part_id, usine_id)
left join dim       using (part_id, usine_id)
left join visuel    using (part_id, usine_id)
left join emballage using (part_id, usine_id)
