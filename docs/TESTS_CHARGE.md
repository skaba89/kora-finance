# Tests de charge (k6)

`make load` (après `make up` et `make seed`) rejoue une journée type en
**lecture seule** sur le dossier de démonstration : liste des dossiers, tableau
de bord, écritures, balance, états financiers, ventes. Aucune écriture : pas
d'effet comptable, rejouable à volonté. Script : `infra/load/parcours-lecture.js` ;
image `grafana/k6:1.4.2` (officielle, épinglée), profil Compose `load`, hors
budget de ressources comme les autres outils (jamais déployée).

Réglages : `KORA_LOAD_VUS` (défaut 20 utilisateurs virtuels), `KORA_LOAD_DURATION`
(défaut 2 min de palier, plus 30 s de montée et 15 s de descente).

## Seuils (objectifs de service initiaux)

< 1 % d'erreurs, 99 % de contrôles réussis, p95 < 800 ms et p99 < 2 s sur
l'ensemble, p95 < 1,5 s sur la balance et les états financiers. Le test échoue
si un seuil est dépassé. À confirmer sur l'infrastructure de production.

## Référence mesurée (2026-11-25, poste local Docker Desktop, `main` 69a4ca5)

| Mesure | 20 VU, 2 min |
|---|---|
| Requêtes / erreurs | 3 057 / 0 (0 %) |
| Médiane / p95 / p99 | 21 ms / 352 ms / 656 ms |
| Balance + états (p95) | 429 ms |
| Maximum observé | 9,15 s (états lourds, cas isolé) |

Constat : des pics isolés au-delà de 9 s existaient alors que p99 restait sous 700 ms.

## Diagnostic des pics (2026-11-25)

Le journal des requêtes lentes (`kora.slow_requests`, seuil `KORA_SLOW_REQUEST_MS`,
1 000 ms par défaut) a montré que toutes les requêtes lentes tombaient **dans la
même seconde, pool PostgreSQL saturé** (15 connexions sur 15, débordement 10/10) :
attente de connexion, pas requête lente. FastAPI sert jusqu'à 40 requêtes
simultanées par processus alors que le pool était de 5 + 10.

Correctif : pool configurable (`KORA_DB_POOL_SIZE`, `KORA_DB_MAX_OVERFLOW`),
porté à 10 + 20. Les connexions s'ouvrent à la demande : worker (4 fils) et
planificateur n'en utilisent que quelques-unes ; total réel < 40 pour
`max_connections` = 100.

| 20 VU, 2 min, même image reconstruite | p95 | p99 | max | requêtes lentes |
|---|---|---|---|---|
| Pool 5 + 10, essai 1 | 41 ms | 94 ms | 1,86 s (connexion, Argon2) | 1 |
| Pool 5 + 10, essai 2 | 95 ms | 410 ms | 2,63 s | 21 (pool saturé) |
| Pool 10 + 20, essais 1 à 3 | 49-53 ms | 110-138 ms | 338-500 ms | 0 |

La première référence (p95 352 ms, max 9,15 s) avait été mesurée sur une image
plus ancienne déjà en service : non comparable directement.

## Limites (non couvert)

- Mesure sur poste de développement, **pas** sur le VPS de production.
- Lecture seule : saisie, validation d'écritures, imports, exports et envois
  d'emails non chargés (effets de bord, quotas et limitation de débit dédiés).
- Un seul dossier de démonstration ; pas de volumétrie multi-dossiers.
- Non exécuté en CI (durée et variabilité des exécuteurs partagés).
