import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from db import query, db_ready

st.set_page_config(page_title="OEE", page_icon="⚙️", layout="wide")
st.title("⚙️ OEE — Overall Equipment Effectiveness")
st.caption("Source: M2 Usinage CNC  |  Performance × Qualité × Disponibilité")

if not db_ready():
    st.error("Warehouse introuvable.")
    st.stop()

with st.sidebar:
    st.header("Filtres")
    usines = st.multiselect("Usine", ["Usine_A", "Usine_B"], default=["Usine_A", "Usine_B"])
    _raw_machines = query(
        "SELECT DISTINCT id_machine FROM gold.mart_oee_par_machine "
        "WHERE id_machine IS NOT NULL ORDER BY 1"
    )["id_machine"].tolist()
    machines = [str(m) for m in _raw_machines if m is not None]
    sel_machines = st.multiselect("Machine", machines, default=machines)

if not usines or not sel_machines:
    st.warning("Sélectionne au moins une usine et une machine.")
    st.stop()

usine_str   = "','".join(str(u) for u in usines)
machine_str = "','".join(str(m) for m in sel_machines)

df = query(f"""
    SELECT * FROM gold.mart_oee_par_machine
    WHERE usine_id   IN ('{usine_str}')
      AND id_machine IN ('{machine_str}')
    ORDER BY date, usine_id, id_machine
""")

if df.empty:
    st.warning("Aucune donnée pour cette sélection.")
    st.stop()

# ── KPIs ─────────────────────────────────────────────────────────────────────
st.subheader("Indicateurs globaux")
k1, k2, k3, k4 = st.columns(4)
k1.metric("OEE moyen",         f"{df['oee_pct'].mean()*100:.1f} %")
k2.metric("Taux qualité moy.", f"{df['taux_qualite_pct'].mean():.1f} %")
k3.metric("Performance moy.",  f"{df['taux_performance_pct'].mean():.1f} %")
k4.metric("Alarmes totales",   f"{int(df['nb_alarmes'].sum()):,}")

st.divider()

# ── OEE Gauges ───────────────────────────────────────────────────────────────
st.subheader("OEE par usine")
cols = st.columns(len(usines))
for i, usine in enumerate(usines):
    sub = df[df["usine_id"] == usine]
    if sub.empty:
        continue
    oee_val = sub["oee_pct"].mean() * 100
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=round(oee_val, 1),
        title={"text": usine},
        gauge={
            "axis": {"range": [0, 100]},
            "bar":  {"color": "#1f77b4" if i == 0 else "#ff7f0e"},
            "steps": [
                {"range": [0, 65],  "color": "#fdd"},
                {"range": [65, 85], "color": "#ffd"},
                {"range": [85, 100],"color": "#dfd"},
            ],
            "threshold": {"line": {"color": "green", "width": 3}, "value": 85},
        },
        number={"suffix": "%"},
    ))
    fig.update_layout(height=280, margin=dict(t=40, b=10))
    cols[i].plotly_chart(fig, use_container_width=True)

st.divider()

# ── Evolution OEE ─────────────────────────────────────────────────────────────
st.subheader("Evolution OEE dans le temps")
fig_line = px.line(
    df, x="date", y="oee_pct", color="usine_id", line_dash="id_machine",
    markers=True,
    labels={"oee_pct": "OEE", "date": "Date", "usine_id": "Usine", "id_machine": "Machine"},
    color_discrete_sequence=["#1f77b4", "#ff7f0e"],
    template="plotly_white",
)
fig_line.update_yaxes(tickformat=".0%", range=[0, 1.05])
st.plotly_chart(fig_line, use_container_width=True)

# ── Breakdown ─────────────────────────────────────────────────────────────────
left, right = st.columns(2)

with left:
    st.subheader("Qualité vs Performance par machine")
    avg_by_machine = df.groupby(["usine_id", "id_machine"], as_index=False).agg(
        qualite=("taux_qualite_pct", "mean"),
        performance=("taux_performance_pct", "mean"),
    )
    fig_sc = px.scatter(
        avg_by_machine, x="performance", y="qualite",
        color="usine_id", text="id_machine",
        labels={"performance": "Performance (%)", "qualite": "Qualité (%)"},
        color_discrete_sequence=["#1f77b4", "#ff7f0e"],
        template="plotly_white",
    )
    fig_sc.update_traces(textposition="top center", marker_size=12)
    fig_sc.add_hline(y=98, line_dash="dot", line_color="green", annotation_text="Cible qualité 98%")
    fig_sc.add_vline(x=97, line_dash="dot", line_color="orange", annotation_text="Cible perf 97%")
    st.plotly_chart(fig_sc, use_container_width=True)

with right:
    st.subheader("Usure outil & Alarmes")
    fig_bar = px.bar(
        df, x="date", y="usure_outil_moy_pct", color="usine_id",
        facet_col="id_machine", barmode="group",
        labels={"usure_outil_moy_pct": "Usure outil (%)"},
        color_discrete_sequence=["#1f77b4", "#ff7f0e"],
        template="plotly_white",
    )
    st.plotly_chart(fig_bar, use_container_width=True)

# ── Raw data ─────────────────────────────────────────────────────────────────
with st.expander("Données brutes"):
    st.dataframe(df, use_container_width=True, hide_index=True)
