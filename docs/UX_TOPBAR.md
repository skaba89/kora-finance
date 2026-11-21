# Kora Premium — Lot 2C, barre supérieure et sélecteur de dossier

- `TopBar` : structure serveur partagée, accès permanent à la liste des dossiers,
  profil et sécurité accessibles sur mobile, disposition adaptative.
- `CompanySwitcher` : select natif et bouton explicite (aucune navigation au
  changement de sélection), options issues uniquement de `getCompanies()`.
  Le serveur ne transmet que l'identifiant, le nom et le rôle traduit des dossiers
  autorisés. Changer de dossier ouvre son tableau de bord, sans conserver les
  identifiants de transaction ou filtres d'un autre tenant.
- Lecture sous Suspense ; aucun changement aux Server Actions, à l'authentification,
  aux permissions, à la synchronisation hors connexion ou aux API.
- Bandeau email : tokens sémantiques et conteneur aligné sur le shell.
- Recette Playwright : deux dossiers, confirmation explicite, locale FR/EN et
  retour liste, captures sur Chromium et Pixel 5. Le contrôle tenant reste assuré
  par l'API et ses tests d'isolation existants.

Le sélecteur d'exercice global reste à étudier selon les filtres métier déjà
existants ; aucune période comptable implicite n'est modifiée.
