# =============================================================================
# MECHA — raccourcis de développement
# =============================================================================
.PHONY: help up down logs build rebuild ingest train predict test lint format \
        grafana psql k8s-edge k8s-central k8s-demo demo demo-down demo-logs clean

help:
	@echo "Cibles disponibles :"
	@echo "  up           — lance la stack Docker Compose en arrière-plan"
	@echo "  down         — arrête la stack (volumes préservés)"
	@echo "  logs         — suit les logs de l'API"
	@echo "  build        — (re)construit toutes les images"
	@echo "  rebuild      — purge le cache et reconstruit"
	@echo "  ingest       — exécute le pipeline ETL (Bronze → Silver/Gold + Postgres)"
	@echo "  train        — entraîne les 3 modèles ML"
	@echo "  predict      — exemple de requête POST /predict"
	@echo "  grafana      — ouvre Grafana dans le navigateur (http://localhost:3000)"
	@echo "  psql         — shell SQL sur Postgres"
	@echo "  test         — exécute la suite pytest avec couverture"
	@echo "  lint         — flake8 + black --check"
	@echo "  format       — black (formatage automatique)"
	@echo "  k8s-edge     — applique l'overlay K3s edge"
	@echo "  k8s-central  — applique l'overlay K3s central"
	@echo "  k8s-demo     — applique l'overlay DEMO (stack locale + streamer)"
	@echo "  demo         — lance le streamer DEMO (Compose, profil demo)"
	@echo "  demo-down    — arrête le streamer DEMO"
	@echo "  demo-logs    — suit les logs du streamer DEMO"
	@echo "  clean        — supprime les artefacts locaux (silver, gold, models, logs)"

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f api

build:
	docker compose build

rebuild:
	docker compose build --no-cache

ingest:
	docker compose run --rm etl

train:
	docker compose run --rm trainer

predict:
	curl -sS -X POST http://localhost:8000/predict \
	  -H "Content-Type: application/json" \
	  -d '{"readings":[{"machine_id":1,"target_cycle":30,"consumption_kWh":18,"temperature_C":75,"vibration":2.5,"pressure":55,"cycle_duration":35,"rpm":1500,"voltage":230}]}' \
	  | python -m json.tool

grafana:
	@echo "Grafana : http://localhost:$$(grep '^GRAFANA_PORT' .env | cut -d= -f2 || echo 3000)"
	@echo "Identifiants : voir GF_SECURITY_ADMIN_USER / GF_SECURITY_ADMIN_PASSWORD du .env"

psql:
	docker compose exec postgres psql -U $$(grep '^POSTGRES_USER' .env | cut -d= -f2) -d $$(grep '^POSTGRES_DB' .env | cut -d= -f2)

test:
	pip install -q -r tests/requirements.txt
	PYTHONPATH=services pytest tests/ --cov=services --cov-report=term-missing

lint:
	pip install -q -r tests/requirements.txt
	flake8 services tests
	black --check --line-length=120 services tests

format:
	pip install -q -r tests/requirements.txt
	black --line-length=120 services tests

k8s-edge:
	kubectl apply -k k8s/overlays/edge

k8s-central:
	kubectl apply -k k8s/overlays/central

k8s-demo:
	kubectl apply -k k8s/overlays/demo

demo:
	docker compose --profile demo up -d --build demo

demo-down:
	docker compose --profile demo rm -sf demo

demo-logs:
	docker compose --profile demo logs -f demo

clean:
	rm -rf data/silver/* data/gold/* models/*.joblib models/*.json models/mlruns logs/*
