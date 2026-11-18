"""Vérifie les budgets de ressources et les quotas d'exports (KF-13), sans exécuter
Docker (python3 standard, sans dépendance).

Contrats mécaniques vérifiés sur les sources :
- docker-compose.yml et deploy/vps/compose.yml : chaque service attendu porte
  `deploy.resources.limits` (mémoire et CPU) ; tout service nouveau impose une
  décision explicite (le script échoue jusqu'à ce que son budget soit déclaré) ;
- les outils de développement (profils « tools »/« e2e ») restent explicitement
  hors budget, jamais déployés en production ;
- Redis : `--maxmemory 200mb --maxmemory-policy noeviction` — au-delà du budget,
  les compteurs de débit échouent fermés plutôt qu'un OOM hôte ;
- quota d'exports : réglages `exports_per_user_per_hour`/`exports_per_company_per_hour`,
  compteurs `export-user`/`export-company` dans exports/service.py, erreur 429
  documentée, compteur générique fail-closed (RedisError relancée) dans core/quota.py ;
- transmission des réglages aux conteneurs (les deux Compose).
Exécuté par la CI (job API), après check-supervision.py.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "apps" / "api"

# Budget attendu par service : (mémoire, CPU). Les valeurs valent pour un VPS
# modeste (4 Go) ; toute modification est un choix conscient, revu au diff.
BUDGETS: dict[str, dict[str, tuple[str, str]]] = {
    "docker-compose.yml": {
        "postgres": ("1g", "1.0"),
        "redis": ("256m", "0.5"),
        "mailpit": ("256m", "0.5"),
        "storage": ("512m", "1.0"),
        "storage-init": ("128m", "0.5"),
        "migrate": ("256m", "0.5"),
        "api": ("512m", "1.0"),
        "worker": ("512m", "1.0"),
        "scheduler": ("128m", "0.25"),
        "backup": ("512m", "1.0"),
        "web": ("512m", "0.5"),
    },
    "deploy/vps/compose.yml": {
        "postgres": ("1g", "1.0"),
        "redis": ("256m", "0.5"),
        "migrate": ("256m", "0.5"),
        "api": ("512m", "1.0"),
        "worker": ("512m", "1.0"),
        "scheduler": ("128m", "0.25"),
        "backup": ("512m", "1.0"),
        "web": ("512m", "0.5"),
        "caddy": ("128m", "0.25"),
    },
}

# Outils de développement (profils) : hors production, sans budget — liste close.
SANS_BUDGET = {"api-tools", "web-tools", "e2e"}


def services(text: str) -> dict[str, str]:
    """Découpe la section `services:` en blocs nommés (indentation 2 espaces)."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.rstrip() == "services:")
    blocks: dict[str, list[str]] = {}
    current: str | None = None
    for line in lines[start + 1 :]:
        if line and not line.startswith(" "):  # section suivante (volumes:…)
            break
        if line.startswith("  ") and not line.startswith("   "):
            head = line[2:].split(":")[0].strip()
            current = head if head and not head.startswith("#") else current
            if current:
                blocks.setdefault(current, []).append(line)
        elif current:
            blocks[current].append(line)
    return {name: "\n".join(block) for name, block in blocks.items()}


def check_budgets(compose: str, text: str) -> None:
    found = services(text)
    attendu = BUDGETS[compose]
    inattendus = sorted(set(found) - set(attendu) - SANS_BUDGET)
    if inattendus:
        raise SystemExit(
            f"{compose} : service(s) sans budget déclaré dans check-compose-budgets.py : "
            f"{inattendus} — déclarez memory/cpus puis complétez BUDGETS."
        )
    manquants = sorted(set(attendu) - set(found))
    if manquants:
        raise SystemExit(f"{compose} : service(s) attendu(s) absent(s) : {manquants}")
    for name, (memoire, cpus) in attendu.items():
        block = found[name]
        m_mem = re.search(r"memory:\s*([0-9.]+[a-z]+)", block)
        m_cpu = re.search(r'cpus:\s*"?([0-9.]+)', block)
        if m_mem is None or m_cpu is None:
            raise SystemExit(
                f"{compose} : {name} : deploy.resources.limits (memory/cpus) manquant."
            )
        if (m_mem.group(1), m_cpu.group(1)) != (memoire, cpus):
            raise SystemExit(
                f"{compose} : {name} : budget {m_mem.group(1)}/{m_cpu.group(1)} != "
                f"{memoire}/{cpus} attendu (mettez à jour BUDGETS en conscience)."
            )


def require(label: str, haystack: str, needles: list[str]) -> None:
    for needle in needles:
        if needle not in haystack:
            raise SystemExit(f"{label} : élément de contrat manquant : {needle!r}")


def main() -> int:
    for compose in ("docker-compose.yml", "deploy/vps/compose.yml"):
        text = (ROOT / compose).read_text(encoding="utf-8")
        check_budgets(compose, text)
        require(
            compose,
            text,
            ['"--maxmemory", "200mb"', '"--maxmemory-policy", "noeviction"',
             "KORA_EXPORTS_PER_USER_PER_HOUR", "KORA_EXPORTS_PER_COMPANY_PER_HOUR"],
        )

    require(
        "apps/api/src/kora/core/quota.py",
        (API / "src" / "kora" / "core" / "quota.py").read_text(encoding="utf-8"),
        ["pipe.incr(key)", "pipe.expire(key", "except RedisError:", "raise"],
    )
    require(
        "apps/api/src/kora/core/config.py",
        (API / "src" / "kora" / "core" / "config.py").read_text(encoding="utf-8"),
        ["exports_per_user_per_hour", "exports_per_company_per_hour"],
    )
    require(
        "apps/api/src/kora/exports/service.py",
        (API / "src" / "kora" / "exports" / "service.py").read_text(encoding="utf-8"),
        ['quota.allowed(', '"export-user"', '"export-company"',
         "TooManyRequestsError", "Retry-After"],
    )
    require(
        "apps/api/src/kora/api/v1/exports.py",
        (API / "src" / "kora" / "api" / "v1" / "exports.py").read_text(encoding="utf-8"),
        ['429: {"model": ErrorResponse}'],
    )

    print("Budgets et quotas vérifiés (KF-13) : limits memory/cpus sur chaque service,")
    print("Redis maxmemory noeviction, quota d'exports fail-closed par utilisateur et dossier.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
