# Kora Finance

Gestion financière et comptable pour les PME guinéennes et les cabinets comptables :
comptabilité SYSCOHADA révisé, rapprochement Mobile Money et bancaire, états financiers
prêts pour un dossier de crédit.

## Démarrage

Prérequis : Docker (avec Compose v2) et `make`. Aucun Node ni Python local n'est nécessaire.

```bash
make env     # génère .env avec des secrets aléatoires
make up      # construit et démarre la pile, attend que tout soit sain
```

| Service | URL |
|---|---|
| Application web | http://127.0.0.1:3100 |
| API | http://127.0.0.1:8100 — docs : http://127.0.0.1:8100/api/docs |
| PostgreSQL | 127.0.0.1:55432 (rôles `kora_owner` / `kora_app`, mots de passe dans `.env`) |
| Redis | 127.0.0.1:56379 |

## Vérifications

```bash
make check   # lint, typage, tests API et web, contrat d'API (comme la CI)
make e2e     # tests de bout en bout Playwright (desktop + mobile)
make help    # toutes les commandes
```

Documentation projet : `CLAUDE.md` (architecture, règles, décisions, avancement),
`docs/PLAN.md` (phases et critères d'acceptation), `worklog.md` (journal daté).
