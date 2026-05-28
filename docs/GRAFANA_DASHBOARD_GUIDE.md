# Guide — Créer un dashboard Grafana sur les données MECHA

Ce guide s'adresse à toute personne (data analyst, dev, responsable maintenance)
qui veut **construire un dashboard Grafana custom** sur les données du projet
MECHA, sans avoir à plonger dans le code.

Tu apprendras :
1. Comment te connecter à Grafana
2. Quelles **sources de données** sont disponibles et leur schéma exact
3. Quels **endpoints API** tu peux appeler depuis un panel ou un script
4. Comment **créer un dashboard pas à pas** (avec un exemple complet)
5. Un **cookbook de requêtes** prêtes à copier-coller
6. Comment **exporter ton dashboard** pour le versionner

---

## 1. Connexion à Grafana

### 1.1 URLs selon le déploiement

| Déploiement | URL | Quand l'utiliser |
|---|---|---|
| Docker Compose | http://localhost:3000 | Démo locale rapide |
| Kubernetes (Docker Desktop) | http://localhost:3000 *(après `kubectl port-forward svc/grafana 3000:3000 -n mecha-local`)* | Démo K8s locale |
| K3s site/usine | https://grafana.mecha.local | Production (Ingress Traefik) |

### 1.2 Identifiants par défaut

```
Username : admin
Password : mecha_change_me
```

*(Ces valeurs sont définies par `GF_SECURITY_ADMIN_USER` et `GF_SECURITY_ADMIN_PASSWORD`
dans le `.env`. À changer pour la production.)*

### 1.3 Repérage rapide

Une fois loggé, l'interface :
- **Menu gauche** → icône grille (Dashboards) : tous les dashboards
- **Menu gauche** → icône engrenage (Connections / Data sources) : les sources de données
- **Menu gauche** → icône `+` : créer un nouveau dashboard

Tu trouveras déjà **3 dashboards préinstallés** dans le dossier `MECHA` :
- *MECHA — Vue parc* — utile comme base d'inspiration
- *MECHA — Capteurs (séries temporelles)* — patterns pour graphs temporels
- *MECHA — Santé de l'API* — patterns pour métriques Prometheus

---

## 2. Sources de données disponibles

Deux sources sont préconfigurées et **prêtes à interroger** sans rien faire :

| Datasource Grafana | Type | Pour quoi |
|---|---|---|
| `MECHA-Postgres` *(défaut)* | PostgreSQL | Données métier : capteurs, interventions, prédictions |
| `MECHA-Prometheus` | Prometheus | Métriques infra/applicatives de l'API en temps réel |

### 2.1 Datasource `MECHA-Postgres`

Base PostgreSQL 16 contenant **4 tables** et **2 vues**. Toutes les colonnes
nommées en `"camelCase"` ou avec un underscore doivent être entre **guillemets
doubles** dans les requêtes SQL.

#### Table `sensor_data` — séries temporelles capteurs (~15 000 lignes)

| Colonne | Type | Description |
|---|---|---|
| `machine_id` | `INTEGER` | Identifiant de la machine (1, 2, 3) |
| `target_cycle` | `INTEGER` | Cycle de maintenance cible en heures (30, 60, 10) |
| `"timestamp"` | `TIMESTAMPTZ` | Date/heure de la mesure |
| `"consumption_kWh"` | `DOUBLE PRECISION` | Consommation électrique (kWh) |
| `"temperature_C"` | `DOUBLE PRECISION` | Température (°C) |
| `vibration` | `DOUBLE PRECISION` | Vibration (mm/s) |
| `pressure` | `DOUBLE PRECISION` | Pression (bar) |
| `cycle_duration` | `DOUBLE PRECISION` | Durée du cycle de production |
| `rpm` | `DOUBLE PRECISION` | Rotations par minute |
| `voltage` | `DOUBLE PRECISION` | Tension (V) |
| `failure` | `INTEGER` | 1 = panne déclarée dans la fenêtre, 0 sinon |

**Index** : `(machine_id, "timestamp" DESC)`

#### Table `interventions` — log des défaillances réelles (~363 lignes)

| Colonne | Type | Description |
|---|---|---|
| `machine_id` | `INTEGER` | Machine concernée |
| `"timestamp"` | `TIMESTAMPTZ` | Date/heure de l'intervention |
| `failure_type` | `TEXT` | `"Breakage"` ou `"Overheat"` |
| `temperature` | `DOUBLE PRECISION` | Température au moment de la panne |
| `rpm` | `DOUBLE PRECISION` | RPM au moment de la panne |
| `vibration` | `DOUBLE PRECISION` | Vibration au moment de la panne |
| `pressure` | `DOUBLE PRECISION` | Pression au moment de la panne |

#### Table `feature_snapshot` — dernier point Gold par machine

Contient toutes les features engineerées (rolling means, deltas, load_proxy, etc.)
pour la **dernière mesure connue** de chaque machine. Utile pour les KPIs en
temps réel sans recalcul.

| Colonne | Type | Description |
|---|---|---|
| `machine_id` | `INTEGER` | Machine |
| `target_cycle` | `INTEGER` | Cycle cible |
| `"timestamp"` | `TIMESTAMPTZ` | Date de la mesure |
| *... toutes les colonnes de `sensor_data` ...* | | |
| `"temperature_C_roll_mean_10"` | `DOUBLE PRECISION` | Moyenne mobile sur 10 mesures |
| `"temperature_C_roll_std_10"` | `DOUBLE PRECISION` | Écart-type mobile sur 10 mesures |
| `"temperature_C_delta"` | `DOUBLE PRECISION` | Gradient (différence avec mesure précédente) |
| `vibration_roll_mean_10` | `DOUBLE PRECISION` | Idem pour vibration |
| `vibration_roll_std_10` | `DOUBLE PRECISION` | |
| `vibration_delta` | `DOUBLE PRECISION` | |
| `pressure_roll_mean_10` | `DOUBLE PRECISION` | Idem pour pression |
| `pressure_roll_std_10` | `DOUBLE PRECISION` | |
| `pressure_delta` | `DOUBLE PRECISION` | |
| `load_proxy` | `DOUBLE PRECISION` | `rpm × pressure / (|voltage|+1)` — charge mécanique normalisée |
| `energy_per_cycle` | `DOUBLE PRECISION` | `consumption_kWh × cycle_duration` |
| `hours_since_last_intervention` | `DOUBLE PRECISION` | Heures depuis la dernière panne déclarée |
| `failure_type` | `TEXT` | `"none"` / `"Breakage"` / `"Overheat"` au moment du snapshot |

#### Table `predictions` — historique des prédictions de l'API (s'accumule)

| Colonne | Type | Description |
|---|---|---|
| `id` | `BIGSERIAL PRIMARY KEY` | Identifiant unique auto-incrémenté |
| `recorded_at` | `TIMESTAMPTZ` | Quand la prédiction a été faite |
| `machine_id` | `INTEGER` | Machine prédite |
| `model_version` | `TEXT` | Version du modèle (timestamp d'entraînement) |
| `threshold` | `DOUBLE PRECISION` | Seuil d'alerte utilisé (typiquement 0.75) |
| `failure_probability` | `DOUBLE PRECISION` | Proba de défaillance ∈ [0, 1] |
| `predicted_failure_type` | `TEXT` | `"none"` / `"Breakage"` / `"Overheat"` |
| `predicted_rul_hours` | `DOUBLE PRECISION` | Durée résiduelle estimée (heures) |
| `alert_level` | `TEXT` | `"nominal"` / `"warning"` / `"critical"` |

**Index** : `(machine_id, recorded_at DESC)`, `(alert_level, recorded_at DESC)`

#### Vues prêtes à l'emploi

**`v_last_prediction_per_machine`** — dernière prédiction par machine :

```sql
SELECT * FROM v_last_prediction_per_machine;
```

**`v_alerts_daily`** — agrégat des alertes par jour, niveau et type :

```sql
SELECT * FROM v_alerts_daily ORDER BY day DESC LIMIT 30;
```

---

### 2.2 Datasource `MECHA-Prometheus`

Prometheus scrape automatiquement l'API toutes les **15 secondes** et expose
ces métriques :

| Métrique | Type | Labels | Description |
|---|---|---|---|
| `mecha_api_predict_requests_total` | `counter` | `status` ∈ {`ok`, `error`, `unavailable`} | Nombre de requêtes `/predict` reçues |
| `mecha_api_predict_latency_seconds` | `histogram` | — | Latence du endpoint `/predict` (buckets standards) |
| `mecha_api_predictions_total` | `counter` | `machine_id` | Nombre de prédictions par machine |
| `mecha_api_alerts_total` | `counter` | `level` ∈ {`nominal`, `warning`, `critical`} | Alertes émises par niveau |
| `mecha_api_alerts_by_type_total` | `counter` | `failure_type` ∈ {`none`, `Breakage`, `Overheat`} | Alertes par type de panne prédit |

Les métriques `_total` sont des compteurs cumulatifs depuis le démarrage du
pod — utilise `rate()`, `increase()` ou `irate()` pour obtenir des taux.

---

## 3. API REST — endpoints que tu peux appeler

Si tu as besoin de **scorer toi-même** des mesures ou d'afficher des résultats
calculés à la volée (dashboard scripté, alerting externe, intégration GMAO),
voici l'API REST disponible.

**Base URL** :
- Compose local : `http://localhost:8000`
- K8s local : `http://localhost:8000` *(via `kubectl port-forward svc/api 8000:8000 -n mecha-local`)*
- En cluster : `http://api:8000` *(depuis un autre pod, via DNS interne)*

### `GET /health`

État du service et des modèles chargés.

```bash
curl -s http://localhost:8000/health
```

```json
{
  "status": "ok",
  "models_loaded": true,
  "model_trained_at": "20260528T091332Z",
  "type_classes": ["Breakage", "Overheat", "none"],
  "site_id": "docker-desktop",
  "timestamp": "2026-05-28T09:15:48.348802Z"
}
```

### `GET /metrics`

Export Prometheus standard (consommé par le service Prometheus, rarement utile
à appeler manuellement).

### `POST /predict`

Cœur de l'API : reçoit une ou plusieurs mesures capteurs et retourne :
- la probabilité de défaillance (`failure_probability`)
- le type de panne le plus probable (`predicted_failure_type`)
- la durée résiduelle estimée en heures (`predicted_rul_hours`)
- le niveau d'alerte (`alert_level`)

**Limite** : 1 à 1000 mesures par requête.

```bash
curl -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{
    "readings": [{
      "machine_id": 1,
      "target_cycle": 30,
      "consumption_kWh": 18.5,
      "temperature_C": 95.0,
      "vibration": 3.2,
      "pressure": 55.0,
      "cycle_duration": 35.0,
      "rpm": 1550.0,
      "voltage": 230.0
    }]
  }'
```

**Champs d'entrée obligatoires** (par mesure) :

| Champ | Borne acceptée | Unité |
|---|---|---|
| `machine_id` | `>=1` | — |
| `target_cycle` | `>=1`, `<=10000` | heures |
| `consumption_kWh` | `>=0`, `<=1000` | kWh |
| `temperature_C` | `>=-20`, `<=200` | °C |
| `vibration` | `>=0`, `<=50` | mm/s |
| `pressure` | `>=0`, `<=200` | bar |
| `cycle_duration` | `>=0`, `<=300` | min |
| `rpm` | `>=0`, `<=5000` | rpm |
| `voltage` | `>=0`, `<=500` | V |

**Champs dérivés facultatifs** *(si tu ne les fournis pas, l'API les calcule
automatiquement à partir des mesures brutes)* :
- `temperature_C_roll_mean_10`, `temperature_C_roll_std_10`, `temperature_C_delta`
- `vibration_roll_mean_10`, `vibration_roll_std_10`, `vibration_delta`
- `pressure_roll_mean_10`, `pressure_roll_std_10`, `pressure_delta`
- `hours_since_last_intervention`

**Réponse** :

```json
{
  "model_version": "20260528T091332Z",
  "threshold": 0.75,
  "predictions": [{
    "machine_id": 1,
    "failure_probability": 0.83,
    "predicted_failure_type": "Overheat",
    "failure_type_probabilities": {
      "Breakage": 0.12,
      "Overheat": 0.71,
      "none": 0.17
    },
    "predicted_rul_hours": 12.3,
    "alert": true,
    "alert_level": "warning"
  }]
}
```

> **Bonus** : chaque appel `/predict` est **automatiquement persisté** dans la
> table `predictions` (Postgres). Tu n'as donc rien à faire pour qu'il apparaisse
> dans Grafana.

### Documentation interactive OpenAPI

L'API expose Swagger UI sur :

```
http://localhost:8000/docs
```

Tu peux y tester chaque endpoint sans coder.

---

## 4. Créer ton premier dashboard — pas à pas

Objectif : on va créer un dashboard simple **"Comparaison des 3 machines"**
qui montre la consommation électrique moyenne et le nombre d'alertes par
machine.

### Étape 1 — Nouveau dashboard

1. Menu gauche → `+` → **New dashboard**
2. Tu arrives sur une page vide avec un bouton **Add visualization**

### Étape 2 — Premier panneau : consommation moyenne par machine

1. Clique **Add visualization**
2. Choisis la datasource **`MECHA-Postgres`**
3. Tu vois deux modes de requête : *Code* et *Builder*. Bascule sur **Code**.
4. Colle cette requête SQL :

```sql
SELECT
  machine_id::text AS metric,
  AVG("consumption_kWh") AS value
FROM sensor_data
WHERE $__timeFilter("timestamp")
GROUP BY machine_id
ORDER BY machine_id;
```

5. Dans le menu **Format** à droite, choisis **Table**
6. Dans le panneau **Visualization** en haut à droite, choisis **Bar chart**
7. Donne un titre : `Consommation moyenne par machine`
8. Clique **Apply** en haut à droite

### Étape 3 — Deuxième panneau : alertes par jour

1. En haut, clique **Add → Visualization**
2. Datasource : `MECHA-Postgres`
3. Requête :

```sql
SELECT
  date_trunc('day', recorded_at) AS time,
  alert_level AS metric,
  COUNT(*) AS value
FROM predictions
WHERE $__timeFilter(recorded_at)
GROUP BY 1, 2
ORDER BY 1;
```

4. Format : **Time series**
5. Visualization : **Time series** ou **Bar chart**
6. Titre : `Alertes par jour et niveau`
7. **Apply**

### Étape 4 — Troisième panneau : latence API (Prometheus)

1. **Add → Visualization**
2. Datasource : `MECHA-Prometheus`
3. Requête PromQL :

```promql
histogram_quantile(0.95, sum by (le) (rate(mecha_api_predict_latency_seconds_bucket[5m])))
```

4. Légende : `p95`
5. Visualization : **Time series**
6. Dans l'onglet **Standard options** → **Unit** → choisis `seconds (s)`
7. Titre : `Latence /predict (p95)`
8. **Apply**

### Étape 5 — Sauvegarder

1. Icône **disquette** en haut à droite
2. Nom du dashboard : ex. `Mon premier dashboard MECHA`
3. Choix du dossier : `MECHA` (par défaut) ou autre
4. **Save**

C'est fini. Tu as un dashboard avec 3 panneaux qui croisent Postgres et Prometheus.

---

## 5. Cookbook — 12 requêtes prêtes à copier

### 5.1 Stats globales

**Nombre de machines surveillées :**

```sql
SELECT COUNT(DISTINCT machine_id) AS value FROM sensor_data;
```

**Nombre total d'interventions par type :**

```sql
SELECT failure_type AS metric, COUNT(*) AS value
FROM interventions
GROUP BY failure_type;
```

**Pourcentage de mesures en défaillance par machine :**

```sql
SELECT
  machine_id,
  ROUND(100.0 * AVG(failure)::numeric, 2) AS failure_rate_percent
FROM sensor_data
GROUP BY machine_id
ORDER BY machine_id;
```

### 5.2 Séries temporelles capteurs

**Température dans le temps (toutes machines) :**

```sql
SELECT
  "timestamp" AS time,
  machine_id::text AS metric,
  "temperature_C" AS value
FROM sensor_data
WHERE $__timeFilter("timestamp")
ORDER BY "timestamp";
```

**Plusieurs métriques d'une seule machine** *(utiliser une variable `$machine`)* :

```sql
SELECT
  "timestamp" AS time,
  "temperature_C", vibration, pressure, rpm
FROM sensor_data
WHERE machine_id = $machine
  AND $__timeFilter("timestamp")
ORDER BY "timestamp";
```

### 5.3 Prédictions et alertes

**Dernier état par machine (utilise la vue) :**

```sql
SELECT
  machine_id,
  recorded_at,
  ROUND(failure_probability::numeric, 3) AS p_fail,
  predicted_failure_type,
  ROUND(predicted_rul_hours::numeric, 1) AS rul_h,
  alert_level
FROM v_last_prediction_per_machine
ORDER BY machine_id;
```

**Évolution de la probabilité de défaillance par machine :**

```sql
SELECT
  recorded_at AS time,
  machine_id::text AS metric,
  failure_probability AS value
FROM predictions
WHERE $__timeFilter(recorded_at)
ORDER BY recorded_at;
```

**Nombre d'alertes 24h glissantes :**

```sql
SELECT COUNT(*) AS value
FROM predictions
WHERE alert_level <> 'nominal'
  AND recorded_at > NOW() - INTERVAL '24 hours';
```

**Distribution des types de défaillance prédite :**

```sql
SELECT predicted_failure_type AS metric, COUNT(*) AS value
FROM predictions
WHERE $__timeFilter(recorded_at)
GROUP BY predicted_failure_type;
```

### 5.4 Corrélation interventions / capteurs

**Capteurs au moment des dernières pannes :**

```sql
SELECT
  i."timestamp" AS time,
  i.failure_type,
  i.temperature,
  i.vibration,
  i.pressure
FROM interventions i
WHERE $__timeFilter(i."timestamp")
ORDER BY i."timestamp" DESC
LIMIT 100;
```

### 5.5 Métriques Prometheus

**Taux de requêtes /predict (req/s) :**

```promql
sum(rate(mecha_api_predict_requests_total[1m]))
```

**Taux d'erreur :**

```promql
sum(rate(mecha_api_predict_requests_total{status="error"}[5m]))
/
clamp_min(sum(rate(mecha_api_predict_requests_total[5m])), 1e-9)
```

**Latence p50 / p95 / p99 :**

```promql
# p50
histogram_quantile(0.50, sum by (le) (rate(mecha_api_predict_latency_seconds_bucket[5m])))

# p95
histogram_quantile(0.95, sum by (le) (rate(mecha_api_predict_latency_seconds_bucket[5m])))

# p99
histogram_quantile(0.99, sum by (le) (rate(mecha_api_predict_latency_seconds_bucket[5m])))
```

**Nombre de prédictions par machine (taux 1 min) :**

```promql
rate(mecha_api_predictions_total[1m])
```

**Alertes critiques sur la dernière heure :**

```promql
sum(increase(mecha_api_alerts_total{level="critical"}[1h]))
```

---

## 6. Variables de dashboard (filtres dynamiques)

Pour que ton dashboard soit interactif, ajoute des **variables** : des
dropdowns en haut du dashboard qui filtrent tous les panneaux.

### Exemple : filtre par machine

1. Dashboard → icône engrenage → **Variables** → **Add variable**
2. Configuration :

| Champ | Valeur |
|---|---|
| Type | `Query` |
| Name | `machine` |
| Label | `Machine` |
| Data source | `MECHA-Postgres` |
| Query | `SELECT DISTINCT machine_id FROM sensor_data ORDER BY machine_id;` |
| Multi-value | Oui |
| Include All option | Oui |

3. **Save**

Ensuite dans tes requêtes, utilise `WHERE machine_id IN ($machine)`.

### Variables utiles courantes

```sql
-- Liste des machines
SELECT DISTINCT machine_id FROM sensor_data ORDER BY machine_id;

-- Liste des types de défaillance
SELECT DISTINCT failure_type FROM interventions ORDER BY failure_type;

-- Liste des niveaux d'alerte
SELECT DISTINCT alert_level FROM predictions ORDER BY alert_level;
```

---

## 7. Bonnes pratiques

| Conseil | Pourquoi |
|---|---|
| Utilise toujours `$__timeFilter("timestamp")` ou `$__timeFilter(recorded_at)` | Sinon ta requête ne respecte pas le sélecteur de période en haut du dashboard |
| Mets les colonnes avec majuscule entre `"guillemets"` | PostgreSQL fait du case-folding : `temperature_C` doit s'écrire `"temperature_C"` |
| Format **Time series** = `time` + valeurs numériques, format **Table** = colonnes libres | Sinon Grafana ne comprend pas comment dessiner le graphe |
| Cast `machine_id::text` quand tu l'utilises comme label de série | Sinon Grafana le voit comme une valeur numérique |
| Active le refresh auto (en haut à droite, ex. `10s`) | Pour voir les données en quasi-temps réel |
| Définis une **time range** par défaut courte (1h ou 24h) | Pour éviter de charger 14 000+ lignes inutilement |
| Préfixe tes panneaux Prometheus par `rate(...)` ou `increase(...)` | Sinon tu affiches le compteur cumulatif depuis le start du pod |

---

## 8. Exporter et versionner ton dashboard

Une fois ton dashboard prêt, tu peux **l'exporter en JSON** pour le commiter
dans le repo Git du projet — il sera alors **provisionné automatiquement**
au prochain redémarrage de Grafana (Compose ou K8s).

### 8.1 Export

1. Ouvre ton dashboard
2. Icône **partage** en haut → onglet **Export**
3. Coche **Export for sharing externally** *(remplace les UID des datasources par des variables)*
4. **Save to file** → télécharge un `.json`

### 8.2 Ajout au repo

Place le JSON dans :

```
services/grafana/dashboards/04_mon_dashboard.json
```

Au prochain `docker compose up -d` (ou `kubectl apply -k ...`), Grafana le
chargera automatiquement dans le dossier *MECHA*.

> Le provider de dashboards est configuré dans
> [`services/grafana/provisioning/dashboards/dashboards.yml`](../services/grafana/provisioning/dashboards/dashboards.yml)
> avec un rechargement toutes les 30 secondes — tu peux donc déposer ton
> JSON sans redémarrer Grafana.

### 8.3 Sauvegarde manuelle en cas d'urgence

Si tu n'as pas accès au repo, tu peux toujours **partager ton dashboard par URL** :

1. Icône **partage** → onglet **Link**
2. Coche **Lock time range**
3. Copie l'URL → elle contient l'ID du dashboard et le time range

---

## 9. Ressources

- [Documentation officielle Grafana Postgres datasource](https://grafana.com/docs/grafana/latest/datasources/postgres/)
- [Documentation Prometheus PromQL](https://prometheus.io/docs/prometheus/latest/querying/basics/)
- [Documentation OpenAPI MECHA](http://localhost:8000/docs) *(API live)*
- [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) — vision globale technique
- [`docs/RUNBOOK.md`](RUNBOOK.md) — procédures opérationnelles
