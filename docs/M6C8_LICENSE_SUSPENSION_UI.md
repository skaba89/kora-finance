# M6c8 — Interface FR/EN de suspension des licences

Couvre les points 5 et 7 du verrou M6c3 pour la suspension (API livrée en M6c6).

- Page `/administration/licences` (admin plateforme uniquement, 404 sinon) :
  chaque période affiche « Suspendre » ou « Réactiver ».
- Motif obligatoire (3 à 500 caractères, mêmes bornes que l'API), confirmation
  native explicite rappelant l'absence d'effet sur paiements et droits comptables.
- L'état affiché est transmis comme état attendu : une période modifiée
  entre-temps est refusée (409) et le message de l'API est affiché.
- Server Action `changeLicenseSuspensionAction` (BFF, jetons jamais exposés au
  navigateur) ; formulaire fonctionnel sans JavaScript (`ActionForm`).

Tests : `license-suspension-form.test.tsx` (motif requis et borné, confirmation,
annulation sans envoi, erreur API affichée) ; E2E : aucune commande de
suspension pour un dirigeant ordinaire. Le parcours positif admin n'est pas
couvert en E2E (aucun moyen de créer un admin plateforme dans la recette
automatisée) : **recette manuelle FR/EN requise** avant usage en production.
