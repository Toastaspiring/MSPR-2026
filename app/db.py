"""DuckDB connection helper shared by all pages."""
import duckdb
import pandas as pd
import streamlit as st
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "warehouse" / "industrial.duckdb"


@st.cache_resource
def _conn():
    if not DB_PATH.exists():
        return None
    return duckdb.connect(str(DB_PATH), read_only=True)


@st.cache_data(ttl=60)
def query(sql: str) -> pd.DataFrame:
    conn = _conn()
    if conn is None:
        return pd.DataFrame()
    return conn.execute(sql).fetchdf()


def db_ready() -> bool:
    return DB_PATH.exists()
