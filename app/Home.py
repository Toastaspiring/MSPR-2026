import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import streamlit as st
import plotly.express as px
from db import query, db_ready

st.set_page_config(
    page_title="Industrial Data Lake",
    page_icon="🏭",
    layout="wide",
)

# ── Guard ────────────────────────────────────────────────────────────────────
if not db_ready():
    st.error("Warehouse introuvable. Lance `make run` d'abord.")
    st.stop()

# ── Header ───────────────────────────────────────────────────────────────────
st.title("🏭 Industrial Data Lake")
st.caption("Bronze → Silver → Gold  |  DuckDB + dbt  |  Usine A & B")
st.divider()

# ── KPIs ─────────────────────────────────────────────────────────────────────
c1, c2, c3, c4 = st.columns(4)

total_ctrl  = query("SELECT count(*) n FROM silver.stg_m5_controle_qualite")['n'][0]
conformite  = query("SELECT round(avg(case when is_conform then 1.0 else 0.0 end)*100,1) r FROM silver.stg_m5_controle_qualite")['r'][0]
oee_moy     = query("SELECT round(avg(oee_pct)*100,1) r FROM gold.mart_oee_par_machine")['r'][0]
exp         = query("SELECT count(distinct part_id) n FROM silver.stg_m8_emballage")['n'][0]

c1.metric("Pièces contrôlées",  f"{total_ctrl:,}")
c2.metric("Taux de conformité", f"{conformite} %")
c3.metric("OEE moyen CNC",      f"{oee_moy} %")
c4.metric("Pièces expédiées",   f"{exp:,}")

st.divider()

# ── Par usine ─────────────────────────────────────────────────────────────────
st.subheader("Par usine")

usine_stats = query("""
    SELECT
        _source_usine                                                        AS Usine,
        count(*)                                                             AS "Pièces contrôlées",
        round(avg(case when is_conform then 1.0 else 0.0 end)*100, 1)       AS "Conformité %",
        sum(case when not is_conform then 1 else 0 end)                      AS "Rebuts"
    FROM silver.stg_m5_controle_qualite
    GROUP BY _source_usine
    ORDER BY _source_usine
""")

col_a, col_b = st.columns(2)

for _, row in usine_stats.iterrows():
    col = col_a if row['Usine'] == 'Usine_A' else col_b
    with col:
        st.markdown(f"#### {row['Usine']}")
        m1, m2, m3 = st.columns(3)
        m1.metric("Pièces", f"{int(row['Pièces contrôlées']):,}")
        m2.metric("Conformité", f"{row['Conformité %']} %")
        m3.metric("Rebuts", f"{int(row['Rebuts']):,}")

st.divider()

# ── Charts ────────────────────────────────────────────────────────────────────
left, right = st.columns(2)

with left:
    st.subheader("OEE par machine (moy. journalière)")
    oee_df = query("""
        SELECT usine_id, id_machine, round(avg(oee_pct)*100,1) AS oee_pct
        FROM gold.mart_oee_par_machine
        GROUP BY usine_id, id_machine
        ORDER BY usine_id, id_machine
    """)
    fig = px.bar(
        oee_df, x="id_machine", y="oee_pct", color="usine_id",
        barmode="group", labels={"oee_pct": "OEE (%)", "id_machine": "Machine"},
        color_discrete_sequence=["#1f77b4", "#ff7f0e"],
        template="plotly_white",
    )
    fig.update_layout(legend_title="Usine", yaxis_range=[0, 100])
    st.plotly_chart(fig, use_container_width=True)

with right:
    st.subheader("Conformité par jour")
    qual_df = query("""
        SELECT usine_id, date, taux_conformite_pct
        FROM gold.mart_qualite_par_usine
        ORDER BY date, usine_id
    """)
    fig2 = px.line(
        qual_df, x="date", y="taux_conformite_pct", color="usine_id",
        markers=True, labels={"taux_conformite_pct": "Conformité (%)", "date": "Date"},
        color_discrete_sequence=["#1f77b4", "#ff7f0e"],
        template="plotly_white",
    )
    fig2.update_layout(legend_title="Usine", yaxis_range=[0, 100])
    st.plotly_chart(fig2, use_container_width=True)

st.divider()

# ── Pipeline status ────────────────────────────────────────────────────────────
st.subheader("Statut du warehouse")

tables = query("""
    SELECT schema_name AS Schema, table_name AS Table, estimated_size AS "Taille (B)"
    FROM duckdb_tables()
    WHERE schema_name IN ('raw','silver','gold')
    ORDER BY schema_name, table_name
""")

schema_colors = {"raw": "🟫", "silver": "⬜", "gold": "🟡"}
for schema, grp in tables.groupby("Schema"):
    icon = schema_colors.get(schema, "")
    with st.expander(f"{icon} {schema.upper()} — {len(grp)} tables"):
        st.dataframe(grp[["Table", "Taille (B)"]], use_container_width=True, hide_index=True)
