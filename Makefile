.PHONY: install ingest silver gold run test docs clean ui

DBT_FLAGS := --project-dir dbt --profiles-dir dbt

# ── Setup ─────────────────────────────────────────────────────────────────────
install:
	pip install -r requirements.txt

# ── Pipeline ──────────────────────────────────────────────────────────────────
ingest:
	python pipeline/ingestion/loader.py

silver:
	dbt run $(DBT_FLAGS) --select path:models/staging

gold:
	dbt run $(DBT_FLAGS) --select path:models/marts

run: ingest
	dbt run $(DBT_FLAGS)

# ── Quality ───────────────────────────────────────────────────────────────────
test:
	dbt test $(DBT_FLAGS)

# ── Docs ──────────────────────────────────────────────────────────────────────
docs:
	dbt docs generate $(DBT_FLAGS)
	dbt docs serve $(DBT_FLAGS)

# ── UI ────────────────────────────────────────────────────────────────────────
ui:
	streamlit run app/Home.py

# ── Utils ─────────────────────────────────────────────────────────────────────
clean:
	rm -f warehouse/industrial.duckdb
