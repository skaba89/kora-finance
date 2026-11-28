"""Vérifie le versionnement du déploiement VPS (KF-11), sans exécuter Docker.

Contrats mécaniques vérifiés sur les sources :
- compose VPS : les images applicatives sont étiquetées par la variable de release
  ${KORA_IMAGE_TAG:-prod}, jamais par le tag mobile direct kora-api:prod/kora-web:prod ;
- deploy.sh : avance ff-only depuis main, refuse une copie git non propre, identifie la
  release par SHA court, impose la sauvegarde pré-migration vérifiée avant la bascule,
  revient automatiquement à la version précédente en cas d'échec, consigne releases.log ;
- rollback.sh : existe, lit .previous-release, refuse sans version connue, vérifie la
  présence des images et repasse `up -d --wait` sur l'ancien tag ;
- backup.sh / restore.sh : épinglent KORA_IMAGE_TAG sur .release (fallback :prod).
Exécuté par la CI (job API), après check-runtime-db-separation.py.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VPS = ROOT / "deploy" / "vps"


def read(name: str) -> str:
    path = VPS / name
    if not path.exists():
        raise SystemExit(f"deploy/vps/{name} est absent.")
    return path.read_text(encoding="utf-8")


def require(label: str, haystack: str, needles: list[str]) -> None:
    for needle in needles:
        if needle not in haystack:
            raise SystemExit(f"{label} : élément de contrat manquant : {needle!r}")


def refuse(label: str, haystack: str, needles: list[str]) -> None:
    for needle in needles:
        if needle in haystack:
            raise SystemExit(f"{label} : interdiction violée : {needle!r}")


def bash_syntax(name: str) -> None:
    result = subprocess.run(  # noqa: S603 (commande fixe, fichier interne au dépôt)
        ["bash", "-n", str(VPS / name)], capture_output=True, text=True, check=False
    )
    if result.returncode:
        raise SystemExit(f"deploy/vps/{name} : syntaxe bash invalide.\n{result.stderr}")


def main() -> int:
    compose = read("compose.yml")
    require(
        "compose.yml",
        compose,
        ["image: kora-api:${KORA_IMAGE_TAG:-prod}", "image: kora-web:${KORA_IMAGE_TAG:-prod}"],
    )
    refuse(
        "compose.yml",
        compose,
        ["image: kora-api:prod", "image: kora-web:prod"],
    )

    deploy = read("deploy.sh")
    require(
        "deploy.sh",
        deploy,
        [
            "rev-parse --short=12 HEAD",          # release identifiée par SHA
            "--ff-only",                          # avance depuis origin/main (CI verte)
            "ls-remote --exit-code origin refs/heads/main",  # SHA distant frais
            'if [[ "${local_head}" != "${remote_head}" ]]; then',  # aucun commit local
            "impossible de vérifier origin/main",  # échec fermé si hors réseau
            "status --porcelain --untracked-files=no",  # copie git propre
            "./backup.sh",                        # sauvegarde pré-migration imposée
            "KORA_IMAGE_TAG=\"${previous:-prod}\" ./backup.sh",  # backup sur l'image en cours
            "up -d --wait --remove-orphans",      # bascule avec healthchecks
            "KORA_IMAGE_TAG=\"${previous}\" docker compose up -d --wait --remove-orphans || true",  # rollback auto
            "releases.log",                       # consignation des releases
            ".previous-release",                  # cible du rollback connue
            "KORA_PLATFORM_ADMIN_REQUIRE_MFA=",    # garde MFA prod
            "BLOCAGE : MFA des administrateurs plateforme",  # fail closed
            "docker volume inspect kora_postgres_data",  # install persistée détectée
            "KORA_ALLOW_INITIAL_INSTALL",          # opt-in explicite première installation
            "docker volume inspect kora_postgres_data",  # détecte les données persistées
            "docker compose ps -aq postgres",       # refuse un conteneur arrêté
            "PostgreSQL indisponible ou déjà initialisé",  # erreur fermée
        ],
    )

    rollback = read("rollback.sh")
    require(
        "rollback.sh",
        rollback,
        [
            ".previous-release",
            "Aucune version précédente connue",   # refuse sans version connue
            'docker image inspect "kora-api:${previous}"',  # images toujours présentes
            'KORA_IMAGE_TAG="${previous}" docker compose up -d --wait --remove-orphans',
        ],
    )

    for name in ("backup.sh", "restore.sh"):
        script = read(name)
        require(
            name,
            script,
            [
                "KORA_IMAGE_TAG=\"${KORA_IMAGE_TAG:-$(cat .release 2>/dev/null || echo prod)}\"",
            ],
        )

    for name in ("deploy.sh", "rollback.sh", "backup.sh", "restore.sh"):
        bash_syntax(name)

    print("Versionnement du déploiement vérifié (KF-11) : tags par SHA, backup imposé, rollback.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
