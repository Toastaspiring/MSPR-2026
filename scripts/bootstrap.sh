#!/usr/bin/env bash
# =============================================================================
# Bootstrap end-to-end — utile pour la démo MSPR.
# Construit les images, lance la stack, joue le pipeline ETL + entraînement,
# puis affiche les URLs d'accès.
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "1/4 — Préparation de l'environnement..."
[ -f .env ] || cp .env.example .env

echo "2/4 — Construction des images Docker..."
docker compose build

echo "3/4 — Démarrage de la stack..."
docker compose up -d
sleep 5

echo "4/4 — Pipeline ETL + entraînement initial..."
docker compose run --rm etl
docker compose run --rm trainer

GRAFANA_PORT=$(grep -E '^GRAFANA_PORT=' .env 2>/dev/null | cut -d= -f2 || echo 3000)

echo
echo "Stack prête."
echo "  Grafana    : http://localhost:${GRAFANA_PORT}"
echo "  Logs API   : docker compose logs -f api"
echo "  Arrêt      : docker compose down"
