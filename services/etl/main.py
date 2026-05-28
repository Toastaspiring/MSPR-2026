"""Point d'entrée du conteneur ETL.

Exécute le pipeline une fois, puis sort. L'orchestration périodique est
assurée par le service `scheduler` (cf. docker-compose.yml).
"""

from __future__ import annotations

import sys

from .pipeline import run


def main() -> int:
    try:
        run()
        return 0
    except Exception as exc:  # noqa: BLE001
        # log structuré déjà émis dans pipeline.run ; on relève le code retour
        print(f"[ETL] échec : {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
