"use client";

import { useRef } from "react";
import { LogOut } from "lucide-react";

import { Button } from "@/components/ui/button";
import { interpolate } from "@/lib/i18n/interpolate";
import { offlineSupported, purgeUser, unsyncedCount } from "@/lib/offline/store";

/**
 * Déconnexion : efface d'abord ce que l'appareil conserve pour la saisie hors connexion
 * (données du dossier, file d'attente, clé). Si des saisies ne sont pas encore devenues
 * des brouillons, la personne est prévenue et peut renoncer. Sans JavaScript, la
 * déconnexion fonctionne (il n'y a alors rien sur l'appareil).
 */
export function LogoutButton({
  action,
  userId,
  label,
  confirmTemplate,
}: {
  action: () => Promise<void>;
  userId: string;
  label: string;
  confirmTemplate: string;
}) {
  const cleared = useRef(false);
  return (
    <form
      action={action}
      onSubmit={(event) => {
        if (cleared.current || !offlineSupported()) return;
        event.preventDefault();
        const form = event.currentTarget;
        void (async () => {
          try {
            const n = await unsyncedCount(userId);
            if (n > 0 && !window.confirm(interpolate(confirmTemplate, { n }))) return;
            await purgeUser(userId);
          } catch (error) {
            // Stockage illisible : la déconnexion ne doit pas être bloquée.
            console.error("Effacement des données hors connexion impossible", error);
          }
          cleared.current = true;
          form.requestSubmit();
        })();
      }}
    >
      <Button type="submit" variant="outline" size="sm" className="min-h-11 min-w-11 sm:min-h-7 sm:min-w-0" title={label}>
        <LogOut aria-hidden className="size-5 sm:hidden" />
        <span className="sr-only sm:not-sr-only">{label}</span>
      </Button>
    </form>
  );
}
