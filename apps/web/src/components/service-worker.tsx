"use client";

import { useEffect } from "react";

/** Enregistre le service worker (installation PWA, page hors connexion). */
export function ServiceWorkerRegistrar() {
  useEffect(() => {
    if (!("serviceWorker" in navigator)) return;
    navigator.serviceWorker
      .register("/sw.js", { scope: "/" })
      .catch((error: unknown) => console.error("Service worker non enregistré", error));
  }, []);
  return null;
}
