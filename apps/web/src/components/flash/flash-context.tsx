"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

/** Message de confirmation transitoire affiché sous le titre de la page. */
export type Flash = {
  message: string;
  tone: "success";
};

/** Flash stocké : message + page où il a été poussé (contextuel). */
export type StoredFlash = {
  path: string;
  message: string;
};

type FlashContextValue = {
  stored: StoredFlash | null;
  showFlash: (message: string) => void;
  hideFlash: () => void;
  /** Libellé i18n du bouton de fermeture (aria-label). */
  closeLabel: string;
};

const FlashContext = createContext<FlashContextValue | null>(null);

/** Durée d'affichage du bandeau avant effacement automatique. */
export const FLASH_DURATION_MS = 6000;

/**
 * Fournit le bandeau de confirmation à toute la page : les formulaires
 * poussent le message de succès renvoyé par leurs Server Actions et le
 * `PageHeader` l'affiche, visible même sur une page dense (audit UX P2.3,
 * sans librairie de toasts).
 *
 * Le pathname n'est pas lu ici (prerender PPR) : `showFlash` relève la page
 * courante de `window.location` au moment du succès et `FlashBanner` la
 * compare à la sienne — le bandeau est contextuel à la page où il a poussé.
 */
export function FlashProvider({ children, closeLabel }: { children: ReactNode; closeLabel: string }) {
  const [stored, setStored] = useState<StoredFlash | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const hideFlash = useCallback(() => setStored(null), []);

  // Callbacks d'événements (formulaire, clic) : window est disponible.
  const showFlash = useCallback((message: string) => {
    setStored({ path: window.location.pathname, message });
  }, []);

  // Chaque nouveau flash relance le minuteur ; l'ancien est nettoyé au passage.
  useEffect(() => {
    if (!stored) return;
    timerRef.current = setTimeout(hideFlash, FLASH_DURATION_MS);
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [stored, hideFlash]);

  const value = useMemo(
    () => ({ stored, showFlash, hideFlash, closeLabel }),
    [stored, showFlash, hideFlash, closeLabel],
  );

  return <FlashContext.Provider value={value}>{children}</FlashContext.Provider>;
}

/**
 * `null` hors du provider (pages publiques, bandeaux du layout) : dans ce cas
 * les formulaires conservent leur confirmation en place, comme avant.
 */
export function useFlash(): FlashContextValue | null {
  return useContext(FlashContext);
}
