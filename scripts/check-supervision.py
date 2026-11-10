"""Vérifie la supervision d'exploitation (KF-12), sans exécuter Docker.

Contrats mécaniques vérifiés sur les sources :
- kora-backup.service : OnFailure= vers l'unité d'alerte instanciable ;
- kora-alert@.service : modèle présent, appelant alert.sh ;
- contrôle de fraîcheur : kora-freshness.{service,timer} présents, OnFailure=,
  exécution quotidienne après la sauvegarde de 02:30 UTC, script épinglé à la
  release et appelant `backup status --max-age-hours` ;
- sonde externe : kora-probe.{service,timer} présents (toutes les 5 minutes),
  probe.sh interrogeant /health/ready du domaine public avec compteur d'échecs ;
- route Caddy étroite /health/* vers l'API (les sondes sont les seuls chemins
  d'API exposés publiquement) ;
- alert.sh : trace locale puis email via kora.scripts.notify ;
- notification : kora.scripts.notify existe, KORA_ALERT_EMAIL dans la config API,
  le Compose VPS et le modèle d'environnement VPS.
Exécuté par la CI (job API), après check-deploy-versioning.py.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VPS = ROOT / "deploy" / "vps"
API = ROOT / "apps" / "api"


def read(path: Path) -> str:
    if not path.exists():
        raise SystemExit(f"{path.relative_to(ROOT)} est absent.")
    return path.read_text(encoding="utf-8")


def require(label: str, haystack: str, needles: list[str]) -> None:
    for needle in needles:
        if needle not in haystack:
            raise SystemExit(f"{label} : élément de contrat manquant : {needle!r}")


def bash_syntax(path: Path) -> None:
    result = subprocess.run(  # noqa: S603 (commande fixe, fichier interne au dépôt)
        ["bash", "-n", str(path)], capture_output=True, text=True, check=False
    )
    if result.returncode:
        raise SystemExit(f"{path.relative_to(ROOT)} : syntaxe bash invalide.\n{result.stderr}")


def main() -> int:
    require(
        "deploy/vps/kora-backup.service",
        read(VPS / "kora-backup.service"),
        ["OnFailure=kora-alert@%n.service", "ExecStart=__DIR__/backup.sh"],
    )
    require(
        "deploy/vps/kora-alert@.service",
        read(VPS / "kora-alert@.service"),
        ["ExecStart=__DIR__/alert.sh"],
    )
    require(
        "deploy/vps/kora-freshness.service",
        read(VPS / "kora-freshness.service"),
        ["OnFailure=kora-alert@%n.service", "ExecStart=__DIR__/backup-status.sh"],
    )
    require(
        "deploy/vps/kora-freshness.timer",
        read(VPS / "kora-freshness.timer"),
        ["OnCalendar=*-*-* 03:45:00 UTC", "Persistent=true"],
    )
    require(
        "deploy/vps/kora-probe.service",
        read(VPS / "kora-probe.service"),
        ["ExecStart=__DIR__/probe.sh"],
    )
    require(
        "deploy/vps/kora-probe.timer",
        read(VPS / "kora-probe.timer"),
        ["OnCalendar=*:0/5", "Persistent=true"],
    )
    pin = 'KORA_IMAGE_TAG="${KORA_IMAGE_TAG:-$(cat .release 2>/dev/null || echo prod)}"'
    require(
        "deploy/vps/backup-status.sh",
        read(VPS / "backup-status.sh"),
        [pin, "--profile backup", "backup status --max-age-hours 26"],
    )
    require(
        "deploy/vps/alert.sh",
        read(VPS / "alert.sh"),
        [pin, "kora.scripts.notify", "backups/alertes/journal.log", "4 * 3600"],
    )
    require(
        "deploy/vps/probe.sh",
        read(VPS / "probe.sh"),
        ["/health/ready", "KORA_DOMAIN", "backups/sonde-etat", "failures >= 2"],
    )
    require(
        "deploy/vps/Caddyfile",
        read(VPS / "Caddyfile"),
        ["handle /health/*", "reverse_proxy api:8000", "reverse_proxy web:3000"],
    )
    require(
        "deploy/vps/install-backup-timer.sh",
        read(VPS / "install-backup-timer.sh"),
        [
            "kora-backup.service kora-backup.timer",
            "kora-freshness.service kora-freshness.timer",
            "kora-probe.service kora-probe.timer",
            "kora-alert@.service",
        ],
    )
    require(
        "deploy/vps/env.example",
        read(VPS / "env.example"),
        ["KORA_ALERT_EMAIL=__A_REMPLIR__"],
    )
    require(
        "deploy/vps/compose.yml",
        read(VPS / "compose.yml"),
        ["KORA_ALERT_EMAIL: ${KORA_ALERT_EMAIL:-}"],
    )
    require(
        "apps/api/src/kora/core/config.py",
        read(API / "src" / "kora" / "core" / "config.py"),
        ["alert_email: str | None = None"],
    )
    require(
        "apps/api/src/kora/scripts/backup.py",
        read(API / "src" / "kora" / "scripts" / "backup.py"),
        ["def freshness(", "--max-age-hours"],
    )
    notify_path = API / "src" / "kora" / "scripts" / "notify.py"
    require(
        "apps/api/src/kora/scripts/notify.py",
        read(notify_path),
        ["KORA_ALERT_EMAIL", "def notify("],
    )
    for name in ("alert.sh", "backup-status.sh", "probe.sh"):
        bash_syntax(VPS / name)

    print("Supervision vérifiée (KF-12) : alerte OnFailure, fraîcheur quotidienne, sonde externe.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
