# Documentation technique d'architecture

Complète le livrable Word [`MECHA_Architecture_Deploiement.docx`](../MECHA_Architecture_Deploiement.docx)
et détaille les choix d'implémentation côté code.

## 1. Topologie des services

```
Bronze (CSV MECHA)                        Postgres (datastore opérationnel)
  ├── machine_X_targetcycleN.csv          ├── sensor_data          (Silver dénormalisé)
  └── intervention_data_machineN.csv      ├── interventions
                                          ├── feature_snapshot      (dernier Gold par machine)
            │                             ├── predictions           (en temps réel)
            ▼                             └── views opérationnelles
   ┌────────────────┐
   │      etl       │ ──── écrit ────▶  Parquet Silver + Gold + Postgres
   └────────────────┘
            │
            ▼
   ┌────────────────┐
   │    trainer     │ ──── écrit ────▶  models-store (3 .joblib + metadata.json)
   └────────────────┘                    + MLflow tracking local

   ┌────────────────┐    /predict     ┌──────────┐
   │      api       │ ─── lit ──▶ models ─── écrit ──▶ predictions (Postgres)
   └────────────────┘    /metrics  ▲                ▲
                           │       │                │
                           │       └── Prometheus   │
                           │                        │
                           ▼                        │
                    ┌─────────────┐                 │
                    │   Grafana   │ ────────────────┘
                    │ (3 boards)  │
                    └─────────────┘
```

## 2. Modèles ML

| Modèle | Type | Cible | Persistance |
|---|---|---|---|
| `classifier_failure` | RandomForest binaire | `failure` (0/1) | `classifier_failure.joblib` |
| `classifier_type` | RandomForest multi-classes | `failure_type` ∈ {none, Breakage, Overheat} | `classifier_type.joblib` + `type_encoder.joblib` |
| `regressor_rul` | GradientBoostingRegressor | Heures avant prochaine intervention | `regressor_rul.joblib` |

Tous les hyperparamètres sont versionnés dans MLflow (`tracking_uri = file:///models/mlruns`).

## 3. Pipeline Bronze → Silver → Gold

### Bronze → Silver (séries temporelles)
1. Extraction `machine_id` + `target_cycle` depuis le nom de fichier
2. Parsing timestamp UTC
3. Cast numérique des 7 capteurs + `failure`
4. Bornage outliers par capteur (plages physiques)
5. **Imputation linéaire des NaN** par machine (interpolation + ffill/bfill)
6. Suppression des lignes sans timestamp valide
7. Déduplication `(machine_id, timestamp)` — dernière mesure conservée

### Bronze → Silver (interventions)
1. Filtrage des `failure_type` reconnus (Breakage / Overheat)
2. Suppression des timestamps invalides
3. Tri chronologique par machine

### Silver → Gold (feature engineering)
- Rolling mean/std sur 10 mesures pour température, vibration, pression
- Delta (gradient temporel)
- `load_proxy = rpm × pressure / (|voltage| + 1)`
- `energy_per_cycle = consumption_kWh × cycle_duration`
- **Jointure as-of avec interventions** : `hours_since_last_intervention` (backward) + `failure_type` (nearest dans ±1 h)

## 4. Découplage et résilience

Le modèle « écriture fichier + watch mtime » est utilisé volontairement plutôt qu'un message bus pour :

1. Réduire les dépendances pour la DSI MECHA
2. Permettre la **dégradation gracieuse** : si le trainer est en panne, l'API continue d'utiliser le modèle précédent
3. Faciliter l'audit (les modèles successifs sont visibles dans le volume)

Postgres dégrade aussi gracieusement : si la BDD est indisponible, l'ETL écrit les Parquet et logge un warning, l'API renvoie quand même ses prédictions sans persister.

## 5. Observabilité

| Aspect | Outil | Implementation |
|---|---|---|
| Logs | loguru | JSON rotation 20 MB / 14 j (`logs-store`) |
| Métriques applicatives | Prometheus + client Python | `/metrics` (Counter, Histogram) |
| Métriques métier | Grafana SQL panels | Vues Postgres (`v_last_prediction_per_machine`, `v_alerts_daily`) |
| Tracking ML | MLflow file store | Volume `models-store` |
| Health | endpoint `/health` | + probes K8s (liveness + readiness) |

## 6. Stratégie de tests

| Niveau | Couverture | Outils |
|---|---|---|
| Unitaire | Transformations pures (`bronze_to_silver_functions`) | pytest + fixtures DataFrame |
| Unitaire | Configuration (`common.config`) | pytest + monkeypatch |
| Intégration | Pipeline ETL bout-en-bout (CSV → Parquet) | pytest + tmp_path |
| Intégration | API FastAPI avec 3 modèles seeded | TestClient |
| Couverture | Toutes branches business | pytest-cov |

**30 tests passent** en moins de 10 secondes.

## 7. Sécurité

- **Conteneurs** : `USER mecha` (uid 1001) ; en K8s : `runAsNonRoot: true`, capabilities `ALL` droppées, escalation des privilèges désactivée
- **Réseau** : `mecha-net` isolé en Compose ; en K8s :
  - `default-deny-ingress` sur tout le namespace
  - L'API n'accepte que Grafana + Prometheus
  - Postgres uniquement depuis api + etl + grafana
  - Prometheus uniquement depuis Grafana
- **Secrets** : jamais en clair ni versionnés. `.env` exclu de Git ; en K8s → `Secret` (recommandation sealed-secrets en prod)
- **Images** : scan Trivy systématique en CI (CRITICAL + HIGH)
- **Postgres** : credentials générés à la volée, mot de passe dans `Secret` K8s

## 8. Migration Compose → K8s

| Compose | K8s |
|---|---|
| `services: ` (long-running) | `Deployment` + `Service` |
| `services: ` (one-shot) | `CronJob` (etl + trainer) |
| `networks:` | `NetworkPolicy` + namespace |
| `volumes:` named | `PersistentVolumeClaim` |
| `env_file:` | `ConfigMap` + `Secret` |
| `ports:` host | `Service ClusterIP` + `Ingress` (Traefik HTTPS) |
| `depends_on: condition: service_healthy` | probes `readiness` |
| Grafana provisioning fichiers | `ConfigMap` mountés en read-only |

La migration ne demande **aucun changement du code applicatif** : seule l'orchestration change.
