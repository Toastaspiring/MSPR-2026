import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import plotly.graph_objects as go
from db import query, db_ready

st.set_page_config(page_title="Traçabilité", page_icon="🔍", layout="wide")
st.title("🔍 Traçabilité pièce")
st.caption("Reconstituez le parcours complet d'une pièce de M1 à M8")

if not db_ready():
    st.error("Warehouse introuvable.")
    st.stop()

# ── Search ────────────────────────────────────────────────────────────────────
col_input, col_usine = st.columns([3, 1])

with col_usine:
    usine = st.selectbox("Usine", ["Usine_A", "Usine_B"])

with col_input:
    prefix = "P-Usine_A" if usine == "Usine_A" else "P-Usine_B"
    example = query(f"""
        SELECT part_id FROM gold.mart_tracabilite_piece
        WHERE usine_id = '{usine}' LIMIT 1
    """)
    placeholder = example["part_id"][0] if not example.empty else f"{prefix}-000001"
    part_id = st.text_input("Identifiant pièce (part_id)", placeholder=placeholder)

if not part_id:
    st.info("Entre un `part_id` pour tracer la pièce.")
    st.stop()

# ── Load ──────────────────────────────────────────────────────────────────────
row_df = query(f"""
    SELECT * FROM gold.mart_tracabilite_piece
    WHERE part_id = '{part_id}' AND usine_id = '{usine}'
""")

if row_df.empty:
    st.error(f"Pièce `{part_id}` introuvable dans `{usine}`.")
    st.stop()

row = row_df.iloc[0]

# ── Status badge ──────────────────────────────────────────────────────────────
is_conform = row.get("is_conform")
badge_color = "#2ca02c" if is_conform else "#d62728"
badge_text  = "CONFORME" if is_conform else "NON-CONFORME"

st.markdown(
    f"<h3>Pièce : <code>{part_id}</code> &nbsp;"
    f"<span style='background:{badge_color};color:white;padding:4px 12px;"
    f"border-radius:12px;font-size:0.8em'>{badge_text}</span></h3>",
    unsafe_allow_html=True,
)

if row.get("rebut_reason"):
    st.warning(f"Motif de rebut : **{row['rebut_reason']}**")

st.divider()

# ── Timeline ──────────────────────────────────────────────────────────────────
STEPS = [
    ("M1 Découpe Laser",        "ts_decoupe_laser",   "status_laser"),
    ("M2 Poinçonneuse",         "ts_poinconneuse",    None),
    ("M2 Usinage CNC",          "ts_cnc",             "cnc_alarmes"),
    ("M3 Perçage/Taraudage",    "ts_percage",         None),
    ("M3 Presse Plieuse",       "ts_presse",          None),
    ("M4 Traitement Thermique", "ts_thermique",       None),
    ("M5 Finition Ébavurage",   None,                 None),
    ("M5 Contrôle Qualité",     "ts_qualite",         None),
    ("M6 Contrôle Dimensionnel",None,                 None),
    ("M7 Contrôle Visuel",      "ts_visuel",          "decision_vis"),
    ("M8 Emballage",            "ts_emballage",       "client"),
]

st.subheader("Parcours de fabrication")

step_cols = st.columns(len(STEPS))
for i, (label, ts_col, extra_col) in enumerate(STEPS):
    ts_val    = row.get(ts_col) if ts_col else None
    extra_val = row.get(extra_col) if extra_col else None
    present   = ts_val is not None and str(ts_val) not in ("", "NaT", "None")

    with step_cols[i]:
        icon  = "✅" if present else "⬜"
        color = "#dfd" if present else "#f5f5f5"
        ts_str = str(ts_val)[:16] if present else "—"
        extra_str = f"<br><small>{extra_val}</small>" if extra_val and str(extra_val) != "nan" else ""

        st.markdown(
            f"<div style='background:{color};border-radius:8px;padding:8px;text-align:center;"
            f"font-size:0.75em;min-height:80px'>"
            f"{icon}<br><b>{label}</b><br>{ts_str}{extra_str}</div>",
            unsafe_allow_html=True,
        )

st.divider()

# ── Attributes by station ──────────────────────────────────────────────────────
st.subheader("Attributs par station")

SECTIONS = {
    "🔩 Matière (M1)": ["type_materiau", "fournisseur", "id_lot_matiere", "taux_chute_pct"],
    "⚙️ CNC (M2)":     ["temps_cycle_reel_s", "cnc_pieces_nok", "usure_cnc_pct", "cnc_alarmes"],
    "📐 Presse (M3)":  ["actual_angle_deg", "angle_deviation_deg"],
    "🔥 Thermique (M4)":["batch_id", "temp_four_c", "durete_sortie_hrc", "courbe_montee_ok", "coating_thickness_um"],
    "✅ Qualité (M5)":  ["is_conform", "final_angle_measure_deg", "visual_score", "rebut_reason", "reprise_manuelle", "defauts_surface_detectes"],
    "📏 Dimensionnel (M6)": ["dim_x_mm", "dim_y_mm", "dim_z_mm", "ecart_nominale_mm", "resultat_dim"],
    "👁️ Visuel (M7)":  ["decision_vis", "gravite_defaut", "photo_url"],
    "📦 Emballage (M8)": ["client", "date_expedition", "num_lot_prod", "certificat_conf"],
}

for section, fields in SECTIONS.items():
    available = {f: row.get(f) for f in fields if f in row.index and str(row.get(f)) not in ("nan", "None", "")}
    if not available:
        continue
    with st.expander(section, expanded=True):
        cols = st.columns(min(len(available), 4))
        for j, (k, v) in enumerate(available.items()):
            cols[j % 4].metric(k, str(v) if v is not None else "—")
