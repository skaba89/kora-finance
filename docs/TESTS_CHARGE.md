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

Constat : des pics isolés au-delà de 9 s existent sur les états financiers alors
que p99 reste sous 700 ms ; cause non diagnostiquée (démarrage à froid, verrou ou
ressources du poste). À investiguer avant d'élever les objectifs.

## Limites (non couvert)

- Mesure sur poste de développement, **pas** sur le VPS de production.
- Lecture seule : saisie, validation d'écritures, imports, exports et envois
  d'emails non chargés (effets de bord, quotas et limitation de débit dédiés).
- Un seul dossier de démonstration ; pas de volumétrie multi-dossiers.
- Non exécuté en CI (durée et variabilité des exécuteurs partagés).
