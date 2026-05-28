-- =============================================================================
-- MECHA — Schéma Postgres (datastore opérationnel pour Grafana)
-- Exécuté automatiquement au premier démarrage du conteneur postgres
-- (les SQL placés dans /docker-entrypoint-initdb.d sont rejoués UNE seule fois,
--  les TRUNCATE en CI/CD remettent à zéro le contenu sans toucher au schéma).
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Séries temporelles capteurs (Silver dénormalisée)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sensor_data (
    machine_id           INTEGER       NOT NULL,
    target_cycle         INTEGER       NOT NULL,
    "timestamp"          TIMESTAMPTZ   NOT NULL,
    "consumption_kWh"    DOUBLE PRECISION,
    "temperature_C"      DOUBLE PRECISION,
    vibration            DOUBLE PRECISION,
    pressure             DOUBLE PRECISION,
    cycle_duration       DOUBLE PRECISION,
    rpm                  DOUBLE PRECISION,
    voltage              DOUBLE PRECISION,
    failure              INTEGER       NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_sensor_data_machine_ts
    ON sensor_data (machine_id, "timestamp" DESC);

-- -----------------------------------------------------------------------------
-- Log des interventions (défaillances réelles déclarées)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS interventions (
    machine_id   INTEGER       NOT NULL,
    "timestamp"  TIMESTAMPTZ   NOT NULL,
    failure_type TEXT          NOT NULL,
    temperature  DOUBLE PRECISION,
    rpm          DOUBLE PRECISION,
    vibration    DOUBLE PRECISION,
    pressure     DOUBLE PRECISION
);

CREATE INDEX IF NOT EXISTS idx_interventions_machine_ts
    ON interventions (machine_id, "timestamp" DESC);
CREATE INDEX IF NOT EXISTS idx_interventions_type
    ON interventions (failure_type);

-- -----------------------------------------------------------------------------
-- Dernier snapshot de features Gold par machine (pour scoring rapide)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS feature_snapshot (
    machine_id                    INTEGER       NOT NULL,
    target_cycle                  INTEGER       NOT NULL,
    "timestamp"                   TIMESTAMPTZ   NOT NULL,
    "consumption_kWh"             DOUBLE PRECISION,
    "temperature_C"               DOUBLE PRECISION,
    vibration                     DOUBLE PRECISION,
    pressure                      DOUBLE PRECISION,
    cycle_duration                DOUBLE PRECISION,
    rpm                           DOUBLE PRECISION,
    voltage                       DOUBLE PRECISION,
    failure                       INTEGER,
    "temperature_C_roll_mean_10"  DOUBLE PRECISION,
    "temperature_C_roll_std_10"   DOUBLE PRECISION,
    "temperature_C_delta"         DOUBLE PRECISION,
    vibration_roll_mean_10        DOUBLE PRECISION,
    vibration_roll_std_10         DOUBLE PRECISION,
    vibration_delta               DOUBLE PRECISION,
    pressure_roll_mean_10         DOUBLE PRECISION,
    pressure_roll_std_10          DOUBLE PRECISION,
    pressure_delta                DOUBLE PRECISION,
    load_proxy                    DOUBLE PRECISION,
    energy_per_cycle              DOUBLE PRECISION,
    hours_since_last_intervention DOUBLE PRECISION,
    failure_type                  TEXT
);

-- -----------------------------------------------------------------------------
-- Prédictions API (alimentées en temps réel)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS predictions (
    id                       BIGSERIAL PRIMARY KEY,
    recorded_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    machine_id               INTEGER     NOT NULL,
    model_version            TEXT        NOT NULL,
    threshold                DOUBLE PRECISION NOT NULL,
    failure_probability      DOUBLE PRECISION NOT NULL,
    predicted_failure_type   TEXT        NOT NULL,
    predicted_rul_hours      DOUBLE PRECISION NOT NULL,
    alert_level              TEXT        NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_predictions_machine_time
    ON predictions (machine_id, recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_predictions_alert
    ON predictions (alert_level, recorded_at DESC);

-- -----------------------------------------------------------------------------
-- Vue d'agrégat : dernière prédiction par machine — utilisée par Grafana
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_last_prediction_per_machine AS
SELECT DISTINCT ON (machine_id)
    machine_id,
    recorded_at,
    model_version,
    failure_probability,
    predicted_failure_type,
    predicted_rul_hours,
    alert_level
FROM predictions
ORDER BY machine_id, recorded_at DESC;

-- -----------------------------------------------------------------------------
-- Compte des alertes par jour — utilisé par Grafana (timeline)
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_alerts_daily AS
SELECT
    date_trunc('day', recorded_at) AS day,
    alert_level,
    predicted_failure_type,
    COUNT(*) AS n_alerts
FROM predictions
WHERE alert_level <> 'nominal'
GROUP BY 1, 2, 3
ORDER BY 1 DESC;
