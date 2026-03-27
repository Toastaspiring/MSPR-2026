import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import plotly.express as px
from db import query, db_ready

st.set_page_config(page_title="Silver Explorer", page_icon="⬜", layout="wide")
st.title("⬜ Silver Explorer")
st.caption("Parcourez les tables nettoyées de la couche Silver")

if not db_ready():
    st.error("Warehouse introuvable. Lance `make run` d'abord.")
    st.stop()

# ── Table selector ────────────────────────────────────────────────────────────
silver_tables = query("""
    SELECT table_name FROM duckdb_tables()
    WHERE schema_name = 'silver'
    ORDER BY table_name
""")["table_name"].tolist()

with st.sidebar:
    st.header("Filtres")
    selected = st.selectbox("Table silver", silver_tables)
    usine_filter = st.multiselect("Usine", ["Usine_A", "Usine_B"], default=["Usine_A", "Usine_B"])

# ── Table info ────────────────────────────────────────────────────────────────
meta = query(f"""
    SELECT column_name AS Colonne, data_type AS Type
    FROM information_schema.columns
    WHERE table_schema = 'silver' AND table_name = '{selected}'
    ORDER BY ordinal_position
""")

row_count = query(f"SELECT count(*) n FROM silver.\"{selected}\"")['n'][0]

col1, col2 = st.columns([2, 1])
with col1:
    st.subheader(f"silver.{selected}")
    st.caption(f"{row_count:,} lignes · {len(meta)} colonnes")

with col2:
    with st.expander("Schéma de la table"):
        st.dataframe(meta, use_container_width=True, hide_index=True)

# ── Data ──────────────────────────────────────────────────────────────────────
usine_list = "', '".join(usine_filter)
where = f"WHERE _source_usine IN ('{usine_list}')" if usine_filter else ""

# Check if _source_usine column exists (galvanisation has batch_id, not part_id)
has_usine_col = "_source_usine" in meta["Colonne"].values
if not has_usine_col:
    where = ""

df = query(f"SELECT * FROM silver.\"{selected}\" {where} LIMIT 500")

st.dataframe(df, use_container_width=True, hide_index=True)

if len(df) == 500:
    st.info("Affichage limité à 500 lignes.")

# ── Stats ─────────────────────────────────────────────────────────────────────
with st.expander("Statistiques descriptives"):
    numerics = df.select_dtypes(include="number")
    if not numerics.empty:
        st.dataframe(numerics.describe().round(3), use_container_width=True)
    else:
        st.write("Aucune colonne numérique.")
