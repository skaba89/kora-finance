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

type FlashContextValue = {
  flash: Flash | null;
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
 */
export function FlashProvider({ children, closeLabel }: { children: ReactNode; closeLabel: string }) {
  const [flash, setFlash] = useState<Flash | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const hideFlash = useCallback(() => setFlash(null), []);

  const showFlash = useCallback((message: string) => {
    setFlash({ message, tone: "success" });
  }, []);

  // Chaque nouveau flash relance le minuteur ; l'ancien est nettoyé au passage.
  useEffect(() => {
    if (!flash) return;
    timerRef.current = setTimeout(hideFlash, FLASH_DURATION_MS);
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [flash, hideFlash]);

  const value = useMemo(
    () => ({ flash, showFlash, hideFlash, closeLabel }),
    [flash, showFlash, hideFlash, closeLabel],
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
