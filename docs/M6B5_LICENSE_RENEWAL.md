# M6b5a — Préparation de renouvellement sans mutation

Le renouvellement continu crée une **nouvelle** période à partir de la
borne de fin exclusive de l'ancienne. La période antérieure est immuable :
aucune mise à jour des dates, des journaux ou des droits métier.

La fonction pure `preview_renewal` conserve le dossier et la version
d'offre publiée, vérifie que la nouvelle date de fin est strictement
ultérieure, et refuse une période suspendue sans décision commerciale
explicite. Le type `paid` est retenu par défaut ; `trial` exige
un choix explicite.

Le stockage futur doit passer par `assign_license`, dont le contrôle
plateforme, la RLS, le journal d'audit et la contrainte anti-chevauchement
restent les autorités effectives. Aucune nouvelle API, migration ou
modification de permission dans ce lot.

Suspension/réactivation auditée et API d'administration : lots suivants,
après vérification des décisions métier et de la non-régression.
