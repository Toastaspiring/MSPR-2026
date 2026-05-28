"""Point d'entrée du conteneur Trainer."""

from __future__ import annotations

import sys

from .train import run


def main() -> int:
    try:
        run()
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"[TRAINER] échec : {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
