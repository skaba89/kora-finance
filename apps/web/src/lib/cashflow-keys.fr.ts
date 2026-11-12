/**
 * Clés i18n de la prévision de trésorerie — à fusionner dans l'objet `fr` de
 * `apps/web/src/lib/i18n/fr.ts` (Phase 3E).
 */
export const cashflowFr = {
  cashflow: {
    title: "Prévision de trésorerie",
    subtitle:
      "Projection 30/60/90 jours : soldes observés, flux engagés (écritures validées datées dans le futur) et flux estimés (moyenne de l'historique). Aucune transaction future n'est inventée.",
    horizon: "Horizon",
    horizonDays: "{n} jours",
    scenario: "Scénario",
    scenarioOptimiste: "Optimiste",
    scenarioNeutre: "Neutre",
    scenarioPrudent: "Prudent",
    status: "Statut",
    openingTotal: "Trésorerie observée",
    lowestBalance: "Solde projeté le plus bas",
    firstCritical: "Première date sous le seuil critique",
    noCritical: "Aucune dans l'horizon",
    insufficientData:
      "Historique insuffisant : la prévision se limite aux soldes observés et aux flux engagés. Elle s'enrichira dès qu'un mois complet d'écritures sera disponible.",
    chartBalance: "Solde projeté",
    chartInflow: "Entrées",
    chartOutflow: "Sorties",
    chartWeek: "Semaine",
    chartTable: "Prévision hebdomadaire des flux et du solde projeté",
    dailyTable: "Détail journalier",
    dailySummary: "{n} jours — dépliez pour le détail",
    date: "Date",
    committedInflow: "Engagés entrée",
    committedOutflow: "Engagés sortie",
    estimatedInflow: "Estimés entrée",
    estimatedOutflow: "Estimés sortie",
    balance: "Solde projeté",
    accounts: "Par compte",
    accountNumber: "Compte",
    accountLabel: "Libellé",
    accountOpening: "Solde observé",
    accountCommitted: "Engagés (net)",
    accountProjected: "Projeté fin d'horizon",
    markLabel: "Projeté J+{n}",
    assumptions: "Comment ce chiffre est calculé",
    assumptionsScenario:
      "Scénario : encaissements estimés ×{inflow}, décaissements estimés ×{outflow}, retard encaissements {delay} j, avance décaissements {advance} j. Les flux engagés ne sont jamais ajustés.",
    assumptionsScope:
      "Périmètre : comptes de classe 5 hors 58x (virements internes). Historique utilisé : {months} mois complets.",
    excludedDrafts: "Brouillons futurs exclus (non validés)",
    noExcludedDrafts: "Aucun brouillon futur touchant la trésorerie.",
    exportPdf: "Exporter en PDF",
    exportXlsx: "Exporter en Excel",
    snapshots: "Instantanés figés",
    snapshotsEmpty: "Aucun instantané figé. Figez la prévision pour suivre sa réalisation.",
    snapshotAt: "Figé le",
    snapshotVsActual: "Comparer au réalisé",
    freeze: "Figer cette prévision",
    freezeDone: "Instantané figé.",
    settings: "Seuils d'alerte",
    criticalFloor: "Seuil critique",
    warningFloor: "Seuil de surveillance",
    warningFloorNone: "Désactivé",
    settingsSaved: "Seuils enregistrés.",
    settingsInvalid:
      "Le seuil de surveillance doit rester supérieur ou égal au seuil critique.",
    expertNotice:
      "Outil d'aide à la décision : la présentation comptable reste à valider par un expert-comptable.",
  },
} as const;
