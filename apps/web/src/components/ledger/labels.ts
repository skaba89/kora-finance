import type { Dictionary } from "@/lib/i18n/server";

import type { EditorLabels } from "./entry-editor";

/** Libellés de l'éditeur (composant client) extraits du dictionnaire côté serveur. */
export function editorLabels(t: Dictionary): EditorLabels {
  const e = t.entries;
  return {
    journal: e.journal,
    date: e.date,
    reference: e.reference,
    referenceHint: e.referenceHint,
    label: e.label,
    account: e.account,
    accountPlaceholder: e.accountPlaceholder,
    lineLabel: e.lineLabel,
    debit: e.debit,
    credit: e.credit,
    totals: e.totals,
    difference: e.difference,
    balanced: e.balanced,
    addLine: e.addLine,
    removeLine: e.removeLine,
    lineN: e.lineN,
    saveDraft: e.saveDraft,
    saveAndPost: e.saveAndPost,
    pending: t.common.pending,
    invalidAmount: e.invalidAmount,
    unknownAccount: e.unknownAccount,
    oneSide: e.oneSide,
    noLines: e.noLines,
  };
}
