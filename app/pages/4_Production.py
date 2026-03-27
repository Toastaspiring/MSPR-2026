import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from db import query, db_ready

st.set_page_config(page_title="Production vs Plan", page_icon="📊", layout="wide")
st.title("📊 Production vs Plan")
st.caption("Source: Production_Plan (objectif) × M8 Emballage (réel expédié)")

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
    SELECT * FROM gold.mart_production_vs_plan
    WHERE usine_id IN ('{usine_str}')
    ORDER BY date, usine_id
""")

if df.empty:
    st.warning("Aucune donnée.")
    st.stop()

# ── KPIs ─────────────────────────────────────────────────────────────────────
total_target = int(df["target_volume_jour"].sum())
total_actual = int(df["actual_volume"].sum())
taux_global  = round(total_actual / total_target * 100, 1) if total_target else 0
ecart_total  = total_actual - total_target

k1, k2, k3, k4 = st.columns(4)
k1.metric("Objectif total",      f"{total_target:,}")
k2.metric("Réel expédié",        f"{total_actual:,}")
k3.metric("Taux de réalisation", f"{taux_global} %")
k4.metric("Ecart cumulé",        f"{ecart_total:+,}", delta_color="normal")

st.divider()

# ── Statut plan ────────────────────────────────────────────────────────────────
st.subheader("Statut par usine et par jour")

status_colors = {"ATTEINT": "#2ca02c", "PROCHE": "#ff7f0e", "EN_RETARD": "#d62728"}

for usine in usines:
    sub = df[df["usine_id"] == usine]
    if sub.empty:
        continue
    st.markdown(f"**{usine}**")
    row_cols = st.columns(len(sub))
    for j, (_, row) in enumerate(sub.iterrows()):
        color = status_colors.get(row["statut_plan"], "#888")
        with row_cols[j]:
            st.markdown(
                f"<div style='border-left:4px solid {color};padding:8px 12px;border-radius:4px;background:#f9f9f9'>"
                f"<b>{row['date']}</b><br>"
                f"Objectif: {int(row['target_volume_jour']):,}<br>"
                f"Réel: {int(row['actual_volume']):,}<br>"
                f"<span style='color:{color};font-weight:bold'>{row['statut_plan']}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )

st.divider()

# ── Graphique comparatif ──────────────────────────────────────────────────────
st.subheader("Objectif vs Réel")

fig = go.Figure()
colors = {"Usine_A": "#1f77b4", "Usine_B": "#ff7f0e"}

for usine in usines:
    sub = df[df["usine_id"] == usine]
    color = colors.get(usine, "#888")

    fig.add_trace(go.Bar(
        name=f"{usine} — Objectif",
        x=sub["date"].astype(str),
        y=sub["target_volume_jour"],
        marker_color=color,
        opacity=0.35,
        legendgroup=usine,
    ))
    fig.add_trace(go.Bar(
        name=f"{usine} — Réel",
        x=sub["date"].astype(str),
        y=sub["actual_volume"],
        marker_color=color,
        legendgroup=usine,
    ))

fig.update_layout(
    barmode="group",
    template="plotly_white",
    xaxis_title="Date",
    yaxis_title="Volume (pièces)",
    legend=dict(orientation="h", y=-0.2),
)
st.plotly_chart(fig, use_container_width=True)

# ── Taux de réalisation ───────────────────────────────────────────────────────
st.subheader("Taux de réalisation (%)")
fig_taux = px.line(
    df, x="date", y="taux_realisation_pct", color="usine_id",
    markers=True,
    labels={"taux_realisation_pct": "Taux (%)", "date": "Date"},
    color_discrete_sequence=["#1f77b4", "#ff7f0e"],
    template="plotly_white",
)
fig_taux.add_hline(y=100, line_dash="dot", line_color="green", annotation_text="Objectif 100%")
fig_taux.add_hline(y=90,  line_dash="dot", line_color="orange", annotation_text="Seuil PROCHE 90%")
st.plotly_chart(fig_taux, use_container_width=True)

with st.expander("Données brutes"):
    st.dataframe(df, use_container_width=True, hide_index=True)
