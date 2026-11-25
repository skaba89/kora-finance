# M6c10 — Interface FR/EN de renouvellement des licences

Interface de l'API M6c9 sur `/administration/licences` (admin plateforme).

- Formulaire proposé uniquement pour la dernière période, non suspendue et
  non expirée (`renewalAvailability`, miroir des refus de l'API qui reste
  l'autorité). Sinon, une note explique pourquoi : réactiver d'abord,
  nouvelle attribution nécessaire (pas de rétroactivité), ou déjà renouvelée.
- Champs : nouvelle fin (date, au plus tôt le lendemain de la fin actuelle),
  type (payante/essai), motif obligatoire (3 à 500 caractères). Le début n'est
  pas saisi : c'est la fin de la période précédente.
- Confirmation explicite : aucun paiement enregistré, période actuelle inchangée.
- Dates calculées en UTC (`nextDay`), comme la consultation de la page.

Tests : `license-renewal-form.test.tsx` (disponibilité, lendemain UTC dont
année bissextile, champs requis, envoi, annulation, erreur API). Parcours
positif admin non couvert en E2E : **recette manuelle FR/EN requise**.
