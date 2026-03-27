# MSPR 2026 — Data Lake Industriel

Pipeline ELT Bronze / Silver / Gold pour les données de production industrielle (Usine A & B), construit avec DuckDB et dbt, avec un tableau de bord Streamlit.

---

## Architecture

```
bronze_data/          Fichiers CSV bruts — source de vérité immuable
pipeline/             Couche d'ingestion Python (Bronze -> schéma raw DuckDB)
dbt/
  models/
    staging/          Couche Silver — 14 modèles (typage, nettoyage, normalisation)
    marts/            Couche Gold   —  4 modèles (OEE, Qualité, Traçabilité, Production vs Plan)
  macros/             Macros SQL partagées (clean_sentinel, normalize_oui_non)
app/                  Tableau de bord Streamlit (5 pages)
warehouse/            Base DuckDB (générée — non committée)
```

**Stack :** Python 3.13 · DuckDB · dbt-core + dbt-duckdb · Streamlit · Plotly

---

## Installation

**1. Installer les dépendances**

```bash
pip install -r requirements.txt
```

**2. Lancer le pipeline complet**

```bash
make run
```

Ingère tous les CSV bronze dans DuckDB, puis exécute tous les modèles dbt (silver + gold).

**3. Lancer le tableau de bord**

```bash
make ui
```

Accessible sur `http://localhost:8501`.

---

## Commandes Make

| Commande | Description |
|---|---|
| `make install` | Installer les dépendances Python |
| `make ingest` | Charger les CSV bronze dans le schéma raw DuckDB |
| `make silver` | Exécuter les modèles dbt staging (couche Silver) |
| `make gold` | Exécuter les modèles dbt marts (couche Gold) |
| `make run` | Pipeline complet : ingest + silver + gold |
| `make test` | Lancer les tests de qualité dbt |
| `make docs` | Générer et servir la documentation dbt |
| `make ui` | Démarrer le tableau de bord Streamlit |
| `make clean` | Supprimer le fichier DuckDB warehouse |

---

## Couches de données

### Bronze
Fichiers CSV sous `bronze_data/Usine_A/` et `bronze_data/Usine_B/`. Jamais modifiés.
28 tables sources couvrant les machines M1 à M8 et le plan de production.

### Silver — `dbt/models/staging/`
Un modèle par machine, fusionnant les deux usines. Transformations appliquées :

- Typage des colonnes (timestamps, numériques, dates)
- Valeurs sentinelles `999.9` remplacées par `NULL`
- Flags `OUI`/`NON` castés en booléen
- Colonnes redondantes supprimées (`id_piece`, `num_serie`, `lot_four`)
- Chaînes vides normalisées en `NULL`

### Gold — `dbt/models/marts/`

| Modèle | Description |
|---|---|
| `mart_oee_par_machine` | OEE proxy (Performance x Qualité x Disponibilité) par machine CNC et par jour |
| `mart_qualite_par_usine` | Taux de conformité et répartition des défauts par usine et par jour |
| `mart_tracabilite_piece` | Parcours complet d'une pièce de M1 à M8, une ligne par pièce |
| `mart_production_vs_plan` | Volume réel expédié vs objectif planifié par usine et par jour |

---

## Pages du tableau de bord

| Page | Description |
|---|---|
| Accueil | KPIs globaux, graphiques OEE et conformité |
| Silver Explorer | Parcourir n'importe quelle table silver avec filtre usine |
| OEE | Jauges, courbes temporelles, scatter qualité vs performance, usure outil |
| Qualité | Jauges de conformité, distribution des défauts, sunburst contrôle visuel |
| Production vs Plan | Barres réel vs objectif, taux de réalisation, statut du plan |
| Traçabilité | Recherche par part_id — parcours station par station de M1 à M8 |

---

## Notes

- `warehouse/industrial.duckdb` n'est pas commité. Régénérer avec `make run`.
- DuckDB ne supporte pas les accès concurrents en lecture-écriture. Arrêter Streamlit avant de lancer `make run`.
- Les profils dbt sont dans `dbt/profiles.yml` — environnement local uniquement, aucune credential externe requise.
