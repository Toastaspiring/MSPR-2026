# MECHA — Solution IA de Maintenance Prédictive

> **MSPR TPRE822** — Bloc 2 — Concevoir une solution IA
> Certification **RNCP36582** — Chef de Projet Expert IA

Architecture de déploiement de bout en bout :

- **Pipeline de données** Bronze (CSV capteurs MECHA) → Silver/Gold Parquet → Postgres
- **3 modèles ML** complémentaires : probabilité de défaillance, type de panne (Breakage / Overheat), durée résiduelle (RUL)
- **API REST** FastAPI exposant les prédictions + métriques Prometheus
- **Dashboards Grafana** provisionnés (vue parc, capteurs temps réel, santé API)
- **Deux niveaux de déploiement** : Docker Compose (prototype) et K3s (industriel multi-sites)

Spécification d'architecture : [`MECHA_Architecture_Deploiement.docx`](MECHA_Architecture_Deploiement.docx)

---

## Architecture Niveau 1 (Docker Compose, livré)

```
                    data/bronze/
                    ├── machine_1_targetcycle30.csv
                    ├── machine_2_targetcycle60.csv
                    ├── machine_3_targetcycle10.csv
                    └── intervention_data_machine{1..3}.csv
                            │
                            ▼
   ┌────────┐     ┌────────────────┐    ┌──────────┐
   │  etl   │────▶│ silver / gold  │───▶│ trainer  │──┐
   └────────┘     │   (Parquet)    │    └──────────┘  │
        │         └────────────────┘                  │ models-store
        │ INSERT                                      ▼ (joblib)
        ▼                ┌──────────┐    ┌──────────────┐
   ┌──────────┐          │   api    │◀───│  3 modèles   │
   │ postgres │◀── INSERT│ (FastAPI)│    │ failure (bin)│
   │          │          └──────────┘    │ failure_type │
   └──────────┘                ▲         │ rul          │
       ▲                       │ /metrics└──────────────┘
       │ SELECT                ▼
       │                ┌─────────────┐
       │                │ prometheus  │
       │                └─────────────┘
       │                       ▲
       │                       │ scrape
   ┌──────────┐                │
   │ grafana  │────────────────┘
   └──────────┘
       ▲
       │ port 3000 (SEUL exposé au host)
   ────┴──────────────────────────────── utilisateur métier
```

**Tous les services** tournent dans le réseau Docker interne `mecha-net`.
Seul **Grafana** publie un port (`3000`) — l'API, Postgres et Prometheus
restent internes.

---

## Composants

| Service | Rôle | Image | Exposition |
|---|---|---|---|
| `postgres` | Stockage opérationnel (séries, interventions, prédictions) | `postgres:16-alpine` | interne `:5432` |
| `etl` | Bronze → Silver/Gold Parquet + alimentation Postgres | `python:3.11-slim` | interne |
| `trainer` | Entraînement Random Forest + GBRT + MLflow | `python:3.11-slim` | interne |
| `api` | REST API + écriture des prédictions en BDD + métriques | `python:3.11-slim` | interne `:8000` |
| `prometheus` | Scrape `/metrics` de l'API toutes les 15 s | `prom/prometheus:v2.54` | interne `:9090` |
| `grafana` | **Dashboards métier provisionnés** | `grafana/grafana:11.2` | **host `:3000`** |
| `scheduler` | Cron interne pour `etl` + `trainer` (APScheduler) | `python:3.11-slim` | interne |
| `demo` | **Rejeu temps réel** du jeu de données (profil `demo`) — fait « bouger » les dashboards | `python:3.11-slim` | interne |

Tous les conteneurs applicatifs tournent en **utilisateur non-root** et sont
issus de **Dockerfiles multi-stage** (section 4.1).

---

## Schéma des données réelles (Bronze)

```
data/bronze/machine_<id>_targetcycle<N>.csv     (séries horaires)
    timestamp, consumption_kWh, temperature_C, vibration, pressure,
    cycle_duration, rpm, voltage, failure

data/bronze/intervention_data_machine<id>.csv   (log des pannes réelles)
    timestamp, failure_type (Breakage|Overheat), temperature, rpm,
    vibration, pressure
```

Le suffixe `targetcycle<N>` indique le **cycle de maintenance cible** de
la machine en heures (30 / 60 / 10 selon la machine). L'ETL extrait
automatiquement `machine_id` et `target_cycle` du nom de fichier.

---

## Arborescence

```
.
├── docker-compose.yml             # orchestration des services (+ `demo` en profil)
├── docker-compose.override.example.yml
├── .env.example                   # toute la configuration applicative
├── Makefile                       # raccourcis (up, ingest, train, predict, …)
├── README.md
├── MECHA_Architecture_Deploiement.docx
│
├── data/
│   ├── bronze/                    # CSV fournis par MECHA (bind-mounted)
│   ├── silver/                    # Parquet nettoyés (volume named)
│   └── gold/                      # Parquet features (volume named)
│
├── services/
│   ├── common/                    # config + logger partagés
│   ├── etl/                       # pipeline + warehouse Postgres
│   ├── trainer/                   # entraînement 3 modèles + MLflow
│   ├── api/                       # FastAPI (schemas, model_loader, warehouse)
│   ├── scheduler/                 # APScheduler (cron)
│   ├── demo/                      # rejeu temps réel (streamer DEMO)
│   ├── postgres/init/             # schéma SQL initial (sensor_data, interventions, predictions, vues)
│   ├── prometheus/                # prometheus.yml
│   └── grafana/                   # provisioning datasources + 4 dashboards JSON
│
├── k8s/
│   ├── base/                      # postgres, prometheus, grafana, api, cronjobs, demo, networkpolicy…
│   └── overlays/{edge,central,docker-desktop,demo}/  # patches Kustomize
│
├── .github/workflows/             # ci.yml + cd.yml
└── tests/                         # 30 tests unit + intégration
```

---

## Démarrage rapide

### Prérequis

- **Docker Engine ≥ 24** et **Docker Compose ≥ 2.20**
- Les CSV MECHA déjà déposés dans `data/bronze/` (déjà présents dans le dépôt)

### 1. Configuration

```bash
cp .env.example .env
# Changer au minimum POSTGRES_PASSWORD et GF_SECURITY_ADMIN_PASSWORD
```

### 2. Lancement de la stack

```bash
make up
# ou : docker compose up -d
```

### 3. Premier cycle complet

```bash
make ingest       # ETL : Bronze CSV → Silver/Gold Parquet → Postgres
make train        # entraîne les 3 modèles (failure, failure_type, RUL)
```

### 4. Accès Grafana

```
http://localhost:3000
identifiants : valeurs de GF_SECURITY_ADMIN_USER / GF_SECURITY_ADMIN_PASSWORD du .env
```

Quatre dashboards sont déjà provisionnés dans le dossier *MECHA* :

1. **Vue parc** — état courant par machine, anomalies 24h, derniers scores
2. **Capteurs** — séries temporelles (température, vibration, pression, rpm, kWh, voltage) filtrables par machine
3. **Santé API** — QPS, latence p50/p95/p99, taux d'erreur, alertes par niveau et par type
4. **DEMO Live** — flux temps réel (rafraîchissement 5 s, fenêtre 15 min) : capteurs et score d'anomalie qui défilent, alimenté par le service `demo`

> **Anomalies, pas pannes** — la solution *classifie des anomalies* : une anomalie n'est pas une panne, mais peut en être le début. Lorsqu'une anomalie est levée, on observe ~75 % de risque de panne sous 24 h.

### 5. Tester l'API

```bash
make predict
# ou directement :
curl -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{"readings":[{"machine_id":1,"target_cycle":30,"consumption_kWh":18,"temperature_C":75,"vibration":2.5,"pressure":55,"cycle_duration":35,"rpm":1500,"voltage":230}]}'
```

Réponse type :

```json
{
  "model_version": "20260528T100000Z",
  "threshold": 0.75,
  "predictions": [{
    "machine_id": 1,
    "failure_probability": 0.83,
    "predicted_failure_type": "Overheat",
    "failure_type_probabilities": {"Breakage": 0.12, "Overheat": 0.71, "none": 0.17},
    "predicted_rul_hours": 12.3,
    "alert": true,
    "alert_level": "warning"
  }]
}
```

Chaque prédiction est aussi **persistée dans Postgres** (table `predictions`), ce qui alimente automatiquement Grafana.

---

## Mode DEMO (graphiques temps réel)

Pour une démonstration, le service `demo` rejoue le jeu de données **comme s'il
arrivait en temps réel** : à chaque tick il insère un lot de mesures dans
`sensor_data` (horodatées à « maintenant ») et appelle l'API `/predict`, qui
calcule les scores et les écrit dans `predictions`. Les dashboards — en
particulier **DEMO Live** — affichent alors des courbes qui défilent.

```bash
make up           # stack de base (postgres, api, grafana, …)
make demo         # lance le streamer (docker compose --profile demo up -d --build demo)
make demo-logs    # suit le flux
make demo-down    # arrête le streamer
```

Source des données (`DEMO_SOURCE`) :

| Valeur | Comportement |
|--------|--------------|
| `auto` (défaut) | rejoue le dernier Parquet Gold s'il existe, sinon génère une trame synthétique réaliste (anomalies injectées) |
| `gold` | rejoue uniquement le Gold (échoue si absent) |
| `synthetic` | génère toujours une trame synthétique — aucun ETL requis |

Réglages (`.env`) : `DEMO_INTERVAL_SECONDS` (cadence), `DEMO_MACHINES`,
`DEMO_SYNTHETIC_POINTS`, `DEMO_LOOP`.

Sur **Kubernetes**, l'overlay dédié déploie la stack locale + le streamer :

```bash
make k8s-demo     # kubectl apply -k k8s/overlays/demo
```

---

## Tests & qualité

```bash
make test         # pytest : 30 tests (unit + intégration)
make lint         # flake8 + black --check
make format       # black --line-length=120
```

La CI exécute la même séquence (cf. [`.github/workflows/ci.yml`](.github/workflows/ci.yml)).

---

## Déploiement K3s (Niveau 2)

```bash
# Sur chaque usine (site)
kubectl apply -k k8s/overlays/edge

# Au siège
kubectl apply -k k8s/overlays/central
```

L'overlay **edge** déploie postgres + grafana + api (1 réplique) + prometheus,
avec le `trainer` suspendu (l'entraînement est centralisé).

L'overlay **central** déploie le même socle avec **3 réplicas d'API**,
HPA jusqu'à 10, et `trainer` actif.

Stratégie de déploiement progressive en 3 phases (section 6.4) :

| Phase | Périmètre | Durée |
|-------|-----------|-------|
| 1 — Pilote | 1 site FR volontaire | 4-8 semaines |
| 2 — Extension FR | 2 sites FR supplémentaires | 2-3 mois |
| 3 — Extension ES | 2 sites ES + cluster central | 2-3 mois |

---

## CI/CD GitHub Actions

| Workflow | Déclencheur | Étapes |
|---|---|---|
| [`ci.yml`](.github/workflows/ci.yml) | push / PR | flake8 → black → pytest → build matriciel (5 services) → scan Trivy |
| [`cd.yml`](.github/workflows/cd.yml) | CI réussie sur `main` ou manuel | `kustomize edit set image` → commit → `kubectl apply` optionnel |

---

## Sécurité & RGPD

- Conteneurs en utilisateur **non-root** (`uid 1001`), capabilities `ALL` droppées
- Réseau interne isolé (`mecha-net` en Compose, **NetworkPolicy default-deny** en K8s)
- **Secrets externalisés** (`.env` jamais commité ; en K8s → `Secret` / sealed-secrets / Vault)
- Scan **Trivy** automatique en CI (CRITICAL + HIGH)
- Logs horodatés rotés (`logs-store`) pour audit
- Jeux de données fournis par MECHA — RGPD : pas de PII, pas de données nominatives

---

## Documentation associée

- [`MECHA_Architecture_Deploiement.docx`](MECHA_Architecture_Deploiement.docx) — spécification complète
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — choix d'implémentation
- [`docs/RUNBOOK.md`](docs/RUNBOOK.md) — procédures opérationnelles
- [`docs/GRAFANA_DASHBOARD_GUIDE.md`](docs/GRAFANA_DASHBOARD_GUIDE.md) — **créer un dashboard custom sur les données MECHA** (schémas, requêtes, API)

---

## Licence

Projet pédagogique — MSPR TPRE822 — RNCP36582 Chef de Projet Expert IA.
