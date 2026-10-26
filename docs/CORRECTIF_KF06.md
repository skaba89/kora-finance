# KF-06 — Compteur de connexion et verrouillage MFA

Audit complémentaire du 26 octobre 2026, base `631d9dc945f7d25892617192637f30acb6ac1ff2`.

## Anomalies vérifiées

| Anomalie | Gravité | Fichier et preuve | Impact | Solution | Validation |
| --- | --- | --- | --- | --- | --- |
| KF-06 : lecture puis écriture du compteur sans verrou | Élevée, P1 | `apps/api/src/kora/auth/service.py`, `login` : lecture simple avant incrément ou remise à zéro. Trois tests PostgreSQL mettent une transaction concurrente en attente, constatent son blocage avec `pg_blocking_pids`, puis vérifient l'état effectivement utilisé. | Perte d'échecs ; connexion possible après verrouillage concurrent du compte, y compris avec un utilisateur déjà chargé dans la session ORM. | `SELECT FOR UPDATE`, rechargement explicite de l'instance ORM et lecture de l'heure après acquisition du verrou. Transaction commune à l'état et à son audit. | Trois cas dans `apps/api/tests/test_login_concurrency.py` : seuil atteint par un échec, compte verrouillé avec mauvais puis bon mot de passe. |
| KF-06 complément MFA : nouveau défi efface les échecs | Élevée, P1 | Même fichier : compteur remis à zéro après le mot de passe, avant validation du second facteur. Le test obtient HTTP 200 au lieu du verrouillage HTTP 423 après plusieurs défis échoués. | Un détenteur du mot de passe peut renouveler les défis pour contourner le compteur du second facteur ; la limitation IP reste distincte. | Remise à zéro seulement après authentification complète : directement pour un compte sans MFA, dans `complete_login` pour un compte MFA. | `test_nouveaux_defis_ne_remettent_pas_les_echecs_mfa_a_zero` et tests de succès TOTP / code de secours dans `apps/api/tests/test_mfa.py`. |

## Reproduction avant correction

Commit de tests seuls : `e5b80d5beace313e4b6024bf6041128f62887c8b`.

[Exécution CI de reproduction](https://github.com/skaba89/kora-finance/actions/runs/40361690329) : quatre nouveaux tests échouent sur les assertions métier attendues ; les 527 tests préexistants passent. Les E2E, le frontend, le contrat, les secrets et la restauration synthétique réussissent.

## Portée et exploitation

Aucune migration ni modification de contrat API. Le verrou utilisateur est conservé pendant la vérification Argon2 et jusqu'au commit : les connexions d'un même compte sont sérialisées, comme la seconde étape MFA. La limitation de débit existante reste nécessaire ; cette correction n'est pas une mesure de capacité ou une protection DDoS.

Tests exécutés sur les bases dédiées de CI uniquement. Aucun accès aux données de production et aucun déploiement effectués.
