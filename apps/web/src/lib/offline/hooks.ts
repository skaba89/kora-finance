"use client";

import { useSyncExternalStore } from "react";

import { offlineSupported } from "./store";

function subscribeOnline(callback: () => void) {
  window.addEventListener("online", callback);
  window.addEventListener("offline", callback);
  return () => {
    window.removeEventListener("online", callback);
    window.removeEventListener("offline", callback);
  };
}

/** État du réseau vu par le navigateur (supposé connecté au rendu serveur). */
export function useOnline(): boolean {
  return useSyncExternalStore(subscribeOnline, () => navigator.onLine, () => true);
}

const never = () => () => undefined;

/** Saisie hors connexion possible sur ce navigateur ; null tant que la page n'est pas hydratée. */
export function useOfflineSupported(): boolean | null {
  return useSyncExternalStore(never, offlineSupported, () => null);
}
