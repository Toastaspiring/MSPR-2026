import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from db import query, db_ready

st.set_page_config(page_title="Qualité", page_icon="✅", layout="wide")
st.title("✅ Contrôle Qualité")
st.caption("Source: M5 Contrôle Qualité · M6 Dimensionnel · M7 Visuel")

if not db_ready():
    st.error("Warehouse introuvable.")
    st.stop()

with st.sidebar:
    usines = st.multiselect("Usine", ["Usine_A", "Usine_B"], default=["Usine_A", "Usine_B"])

if not usines:
    st.warning("Sélectionne au moins une usine.")
    st.stop()

usine_str = "','".join(str(u) for u in usines)

df = query(f"""
    SELECT * FROM gold.mart_qualite_par_usine
    WHERE usine_id IN ('{usine_str}')
    ORDER BY date, usine_id
""")

if df.empty:
    st.warning("Aucune donnée.")
    st.stop()

# ── KPIs ─────────────────────────────────────────────────────────────────────
st.subheader("Résumé global")
k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Total pièces",         f"{int(df['total_pieces'].sum()):,}")
k2.metric("Conformes",            f"{int(df['pieces_conformes'].sum()):,}")
k3.metric("Non-conformes",        f"{int(df['pieces_non_conformes'].sum()):,}")
k4.metric("Rebuts visuels",       f"{int(df['nb_rebuts_visuels'].sum()):,}")
k5.metric("Défauts majeurs",      f"{int(df['nb_defauts_majeurs'].sum()):,}")

st.divider()

# ── Conformité gauges par usine ───────────────────────────────────────────────
st.subheader("Taux de conformité par usine")
cols = st.columns(len(usines))

for i, usine in enumerate(usines):
    sub = df[df["usine_id"] == usine]
    if sub.empty:
        continue
    conf_pct = (sub["pieces_conformes"].sum() / sub["total_pieces"].sum() * 100)
    fig = go.Figure(go.Indicator(
        mode="gauge+number+delta",
        value=round(conf_pct, 2),
        title={"text": usine},
        delta={"reference": 95, "relative": False},
        gauge={
            "axis": {"range": [0, 100]},
            "bar":  {"color": "#2ca02c" if conf_pct >= 95 else "#d62728"},
            "steps": [
                {"range": [0, 90],  "color": "#fdd"},
                {"range": [90, 95], "color": "#ffd"},
                {"range": [95, 100],"color": "#dfd"},
            ],
            "threshold": {"line": {"color": "green", "width": 3}, "value": 95},
        },
        number={"suffix": "%", "valueformat": ".2f"},
    ))
    fig.update_layout(height=280, margin=dict(t=40, b=10))
    cols[i].plotly_chart(fig, use_container_width=True)

st.divider()

# ── Taux conformité par jour ───────────────────────────────────────────────────
left, right = st.columns(2)

with left:
    st.subheader("Taux de conformité par jour")
    fig_conf = px.bar(
        df, x="date", y="taux_conformite_pct", color="usine_id",
        barmode="group",
        labels={"taux_conformite_pct": "Conformité (%)", "date": "Date"},
        color_discrete_sequence=["#1f77b4", "#ff7f0e"],
        template="plotly_white",
    )
    fig_conf.add_hline(y=95, line_dash="dot", line_color="green", annotation_text="Cible 95%")
    fig_conf.update_yaxes(range=[80, 100])
    st.plotly_chart(fig_conf, use_container_width=True)

with right:
    st.subheader("Distribution des motifs de rebut")
    rebut_df = query(f"""
        SELECT
            _source_usine AS usine_id,
            rebut_reason,
            count(*) AS nb
        FROM silver.stg_m5_controle_qualite
        WHERE _source_usine IN ('{usine_str}')
          AND rebut_reason IS NOT NULL
        GROUP BY _source_usine, rebut_reason
        ORDER BY nb DESC
    """)
    if rebut_df.empty:
        st.info("Aucun rebut enregistré.")
    else:
        fig_rebut = px.bar(
            rebut_df, x="rebut_reason", y="nb", color="usine_id",
            barmode="group",
            labels={"nb": "Nombre", "rebut_reason": "Motif"},
            color_discrete_sequence=["#1f77b4", "#ff7f0e"],
            template="plotly_white",
        )
        st.plotly_chart(fig_rebut, use_container_width=True)

st.divider()

# ── Contrôle visuel ─────────────────────────────────────────────────────────
st.subheader("Décisions contrôle visuel (M7)")
visuel_df = query(f"""
    SELECT
        usine_id,
        decision_vis,
        gravite_defaut,
        count(*) AS nb
    FROM gold.mart_tracabilite_piece
    WHERE usine_id IN ('{usine_str}')
      AND decision_vis IS NOT NULL
    GROUP BY usine_id, decision_vis, gravite_defaut
    ORDER BY nb DESC
""")

if not visuel_df.empty:
    # Sunburst requires all leaf values to be non-empty strings
    visuel_df["gravite_defaut"] = visuel_df["gravite_defaut"].replace({"": "AUCUN", None: "AUCUN"}).fillna("AUCUN")
    col_v1, col_v2 = st.columns(2)
    with col_v1:
        fig_dec = px.sunburst(
            visuel_df, path=["usine_id", "decision_vis", "gravite_defaut"], values="nb",
            color="decision_vis",
            color_discrete_map={"OK": "#2ca02c", "RETOUCHE": "#ff7f0e", "REBUT": "#d62728"},
            template="plotly_white",
        )
        fig_dec.update_layout(title="Décisions visuelles par usine")
        st.plotly_chart(fig_dec, use_container_width=True)

    with col_v2:
        st.dataframe(visuel_df, use_container_width=True, hide_index=True)
