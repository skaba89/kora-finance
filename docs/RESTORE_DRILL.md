# Exercice de restauration synthétique — KF-10

Lancer `python3 scripts/restore-drill.py` depuis un poste disposant de Docker Compose.
Le script n'accepte aucune URL, aucun nom de projet ni archive de production.
Il crée des secrets aléatoires, un projet `kora-drill-<identifiant>` et quatre volumes
propres, sans publier de port. Aucun service du Compose de production n'est lancé.
Les clés de cet exercice et les sauvegardes ne sont jamais publiées en artefact.

## Scénario exécuté en CI

1. Initialiser PostgreSQL 16, Redis et Garage source, puis appliquer les migrations.
2. Créer deux sociétés fictives par l'API, avec une écriture validée et un justificatif
   chacune ; activer le MFA pour vérifier aussi la récupération des secrets chiffrés.
3. Capturer les empreintes des lignes visibles sous chaque contexte tenant et plateforme.
4. Produire un vrai `pg_dump -Fc`, l'envoyer avec le mécanisme de sauvegarde chiffrée
   existant et conserver la sauvegarde ainsi que les objets chiffrés hors des volumes.
5. Supprimer le dump en clair puis les volumes PostgreSQL et Garage source.
6. Initialiser PostgreSQL et Garage cibles neufs ; réimporter les objets chiffrés.
7. Vérifier le rejet d'une mauvaise clé, puis déchiffrer le dump avec la clé conservée
   hors des volumes source ; vérifier son SHA-256 et appliquer `pg_restore`.
8. Comparer les empreintes des données, vérifier les trois chaînes d'audit, le rôle
   applicatif sans DDL/BYPASSRLS, FORCE RLS, l'absence de données sans tenant et
   l'immuabilité des écritures validées.
9. Relire par l'API les écritures et justificatifs, vérifier les montants, le refus
   des accès entre sociétés et le déchiffrement des secrets MFA.
10. Nettoyer le projet synthétique et ses volumes, et publier uniquement le rapport JSON.

Les erreurs de connexion hors de ce banc sont refusées avant les opérations SQL/S3.
La CI exige la réussite du job de restauration pour valider son résultat global.

## Preuve produite et limites

`restore-drill-report` contient `restore-drill.json` : résultats, révision de code,
durée totale et temps de récupération synthétique. Aucun mot de passe, clé, JWT,
dump, objet ou manifeste de données n'y figure.

Cet exercice démontre le cycle logiciel sur un petit jeu synthétique, avec disparition
réelle des volumes source. Il ne valide pas le PRA du VPS réel, les volumes métier,
le fournisseur S3 réel, une copie immuable hors compte applicatif, la conservation
organisationnelle des clés, le DNS/proxy, la récupération des files de travail ou les
RPO/RTO contractuels. Le web et le worker ne sont pas redéployés dans cet exercice ;
les contrôles HTTP utilisent l'application FastAPI via son client de test.

Le stockage original n'est pas accessible à la cible : elle utilise un nouveau Garage.
L'archive indépendante et les clés séquestrées sont ici simulées par un répertoire
éphémère privé du runner, conservé hors des volumes supprimés. Cela ne remplace pas
une sauvegarde réellement indépendante dans l'exploitation.

Pour fermer le blocage de production KF-10, répéter ensuite sur une infrastructure
isolée représentative du VPS, avec les copies hors site, l'accès aux clés prévu par
l'exploitation, une release connue et des mesures documentées. Aucune restauration
ni suppression de données de production n'est autorisée par ce script.
