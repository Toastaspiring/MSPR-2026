# Runbook opérationnel — MECHA

Procédures rapides pour les équipes DSI / OPS qui exploitent la solution.

## Démarrer / arrêter

```bash
make up        # docker compose up -d
make down      # docker compose down (volumes conservés)
make logs      # docker compose logs -f api
```

## Diagnostiquer un problème

### Le dashboard affiche « API injoignable »

```bash
docker compose ps                                  # state des conteneurs
docker compose logs --tail=200 api                 # logs API
docker compose exec dashboard \
  python -c "import requests; print(requests.get('http://api:8000/health').json())"
```

Si `model_loaded: false` → exécuter le trainer :

```bash
docker compose run --rm trainer
```

### L'ETL plante sur un fichier CSV

Les logs sont dans le volume `logs-store` (montés sur `/logs/etl/etl.log`).

```bash
docker run --rm -v mecha-logs-store:/logs alpine tail -200 /logs/etl/etl.log
```

### Rollback rapide d'un modèle

Le `trainer` versionne les modèles dans `models-store/mlruns/`. Pour revenir à
une version précédente :

```bash
docker run --rm -it -v mecha-models-store:/models alpine sh
# /models/mlruns/0/<run_id>/artifacts/{classifier,regressor}/model.pkl
# Copier le run souhaité par-dessus /models/classifier.joblib + regressor.joblib
```

L'API détecte la nouvelle `mtime` au prochain appel `/health` ou `/predict`.

## Sauvegarde

Volumes critiques à sauvegarder régulièrement (par exemple par snapshot LVM
ou via `docker run --rm -v mecha-models-store:/from -v $(pwd):/to alpine tar czf /to/models-$(date +%F).tgz -C /from .`) :

- `mecha-gold-data` — historique des features
- `mecha-models-store` — modèles + MLflow

## Mise à jour

```bash
git pull
docker compose pull          # si images publiées via CI/CD
docker compose up -d         # rolling : api/dashboard sans interruption
```

## K3s — opérations courantes

```bash
# Etat global
kubectl -n mecha-edge get pods,svc,ingress,cronjob

# Suivre le déploiement
kubectl -n mecha-edge rollout status deployment/api

# Déclencher un ETL hors planning
kubectl -n mecha-edge create job --from=cronjob/etl etl-manual-$(date +%s)

# Rollback d'un deployment
kubectl -n mecha-edge rollout undo deployment/api
```
