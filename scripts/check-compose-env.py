#!/usr/bin/env python3
"""Toute variable déclarée dans un modèle d'environnement atteint ses conteneurs.

Les fichiers Compose transmettent aux services une liste EXPLICITE de variables
(`x-api-env`). Une variable présente dans `.env` mais absente de cette liste est
ignorée sans erreur : un réglage de sécurité documenté (ex.
KORA_PLATFORM_ADMIN_REQUIRE_MFA) resterait alors sans effet, en silence.

Vérifie, pour chaque couple (modèle d'environnement, fichier Compose), que chaque
variable NON commentée du modèle est référencée par le fichier Compose
(`${VAR}`, `${VAR:-…}`, `${VAR:?…}`), hors variables propres à Docker Compose.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PAIRS = [
    (ROOT / "deploy/vps/env.example", ROOT / "deploy/vps/compose.yml"),
    (ROOT / ".env.example", ROOT / "docker-compose.yml"),
]

# Lues par Docker Compose lui-même, pas par un conteneur.
COMPOSE_OWN = {"COMPOSE_FILE", "COMPOSE_PROFILES", "COMPOSE_PROJECT_NAME"}


def declared(env_text: str) -> set[str]:
    return set(re.findall(r"^([A-Z][A-Z0-9_]*)=", env_text, re.MULTILINE))


def referenced(compose_text: str, name: str) -> bool:
    return re.search(r"\$\{" + re.escape(name) + r"(?:[:?\-}])", compose_text) is not None


def main() -> int:
    errors: list[str] = []
    for env_path, compose_path in PAIRS:
        compose = compose_path.read_text(encoding="utf-8")
        for name in sorted(declared(env_path.read_text(encoding="utf-8")) - COMPOSE_OWN):
            if not referenced(compose, name):
                errors.append(
                    f"{env_path.relative_to(ROOT)} déclare {name}, "
                    f"jamais transmis par {compose_path.relative_to(ROOT)}"
                )
    if errors:
        print("ERREUR : variables d'environnement sans effet :", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print("Variables d'environnement vérifiées : chaque réglage déclaré atteint ses conteneurs.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
