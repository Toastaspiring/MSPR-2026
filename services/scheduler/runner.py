"""Orchestrateur cron des jobs ETL et Trainer.

Le scheduler vit en permanence dans le réseau Docker `mecha-net`. À chaque
échéance, il déclenche l'exécution one-shot des conteneurs `etl` ou
`trainer` via le SDK Docker (socket monté en volume).

Avantage par rapport à un cron host : la planification est versionnée
avec le code, traçable dans les logs et indépendante du système hôte.
"""

from __future__ import annotations

import os
import signal
import sys

import docker
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from common.config import settings
from common.logger import setup_logger

log = setup_logger("scheduler")

# Variables Compose pour cibler les services par nom de conteneur
ETL_SERVICE = os.environ.get("ETL_SERVICE_NAME", "mecha-etl")
TRAINER_SERVICE = os.environ.get("TRAINER_SERVICE_NAME", "mecha-trainer")
COMPOSE_PROJECT = os.environ.get("COMPOSE_PROJECT_NAME", "mecha")


def _docker_client() -> docker.DockerClient:
    return docker.from_env()


def _trigger_service(service_name: str) -> None:
    """Démarre un conteneur one-shot du service.

    On utilise `containers.run` avec `auto_remove=True` pour ne pas
    accumuler de conteneurs morts. Le conteneur monte les mêmes volumes
    nommés que le service principal — c'est `docker compose run` qui s'en
    charge naturellement, mais ici on passe par le SDK pour avoir une
    journalisation centralisée.
    """
    client = _docker_client()
    try:
        # On cherche un conteneur existant (même image, mêmes volumes) pour
        # bénéficier de sa configuration sans la redéfinir.
        existing = client.containers.list(all=True, filters={"name": service_name})
        if not existing:
            log.error("Conteneur introuvable : {}", service_name)
            return

        container = existing[0]
        log.info("Démarrage one-shot : {}", service_name)
        # Stratégie restart : on relance le conteneur arrêté (services
        # `etl` et `trainer` sont définis avec restart: "no" dans Compose).
        container.start()
        # Suivi du log de sortie pour audit
        for line in container.logs(stream=True, follow=True, tail=0):
            try:
                msg = line.decode("utf-8", errors="replace").rstrip()
                if msg:
                    log.info("[{}] {}", service_name, msg)
            except Exception:  # noqa: BLE001
                pass
        result = container.wait()
        log.info("{} terminé — exit={}", service_name, result.get("StatusCode"))
    except docker.errors.DockerException as exc:
        log.error("Erreur Docker pour {} : {}", service_name, exc)


def run_etl() -> None:
    log.info("=== Déclenchement ETL (cron : {}) ===", settings.etl_cron)
    _trigger_service(ETL_SERVICE)


def run_trainer() -> None:
    log.info("=== Déclenchement Trainer (cron : {}) ===", settings.retrain_cron)
    _trigger_service(TRAINER_SERVICE)


def main() -> int:
    log.info("Scheduler démarré — site={}", settings.app_site_id)
    log.info("ETL cron     : {}", settings.etl_cron)
    log.info("Retrain cron : {}", settings.retrain_cron)

    sched = BlockingScheduler(timezone="UTC")
    sched.add_job(
        run_etl,
        CronTrigger.from_crontab(settings.etl_cron, timezone="UTC"),
        id="etl",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )
    sched.add_job(
        run_trainer,
        CronTrigger.from_crontab(settings.retrain_cron, timezone="UTC"),
        id="trainer",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=600,
    )

    def _shutdown(signum, frame) -> None:  # noqa: ARG001
        log.info("Signal {} reçu — arrêt propre du scheduler.", signum)
        sched.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
