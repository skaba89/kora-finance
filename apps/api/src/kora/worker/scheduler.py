"""Planificateur des relances automatiques (Phase B, lot 2).

Lancement : `python -m kora.worker.scheduler` (service compose `scheduler`).

Boucle d'horloge minimale : toutes les `KORA_REMINDER_SCAN_INTERVAL_SECONDS`
(secondes, 3 600 par défaut), le planificateur enfile le balayage
`scan_automatic_reminders` dans la même file que le worker. Séparé du worker :
un worker qui redémarre (déploiement, crash) ne touche pas l'horloge, et le
balayage reste périodique même si le worker est momentanément indisponible.

Idempotence de bout en bout : le balayage enfile une exécution par dossier,
l'exécution ne crée qu'une relance par facture et par jour (unicité en base,
même contrat que la relance 4D) — un tick doublé (deux planificateurs par
mégarde), un tick manqué ou un redémarrage est sans effet négatif. La file
injoignable au moment d'un tick est journalisée : le tick suivant réessaie.
"""

import logging
import time

from kora.core.config import get_settings
from kora.core.logging import configure_logging
from kora.worker import broker as _broker  # noqa: F401  (enregistre le broker)
from kora.worker.tasks import scan_automatic_reminders, scan_import_maintenance

configure_logging(get_settings().log_level)
logger = logging.getLogger(__name__)


def main() -> None:
    settings = get_settings()
    interval = settings.reminder_scan_interval_seconds
    logger.info("planificateur des relances automatiques démarré", extra={"intervalle_s": interval})
    while True:
        try:
            scan_automatic_reminders.send()
        except Exception:
            logger.exception("enfilage du balayage impossible (réessai au prochain tick)")
        try:
            scan_import_maintenance.send()
        except Exception:
            logger.exception("enfilage de la maintenance des imports impossible")
        time.sleep(interval)


if __name__ == "__main__":
    main()
