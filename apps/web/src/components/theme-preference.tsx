"use client";

import { useEffect, useSyncExternalStore } from "react";

type Preference = "system" | "light" | "dark";
const key = "kora-theme";
const eventName = "kora-theme-change";
let fallback: Preference = "system";

function readPreference(): Preference {
  try {
    const value = window.localStorage.getItem(key);
    return value === "light" || value === "dark" || value === "system" ? value : "system";
  } catch {
    return fallback;
  }
}

function subscribe(callback: () => void) {
  window.addEventListener(eventName, callback);
  window.addEventListener("storage", callback);
  return () => {
    window.removeEventListener(eventName, callback);
    window.removeEventListener("storage", callback);
  };
}

const systemPreference = (): Preference => "system";
const systemDark = () => window.matchMedia("(prefers-color-scheme: dark)").matches;
const serverDark = () => false;

function subscribeSystem(callback: () => void) {
  const query = window.matchMedia("(prefers-color-scheme: dark)");
  query.addEventListener("change", callback);
  return () => query.removeEventListener("change", callback);
}

/** Applies only a non-sensitive browser preference, including on cached offline pages. */
export function ThemePreference() {
  const preference = useSyncExternalStore(subscribe, readPreference, systemPreference);
  const dark = useSyncExternalStore(subscribeSystem, systemDark, serverDark);
  useEffect(() => {
    document.documentElement.classList.toggle("dark", preference === "dark" || (preference === "system" && dark));
  }, [preference, dark]);
  return null;
}

export function ThemeSelector({ labels }: { labels: { label: string; system: string; light: string; dark: string } }) {
  const preference = useSyncExternalStore(subscribe, readPreference, systemPreference);
  return (
    <select
      aria-label={labels.label}
      value={preference}
      onChange={(event) => {
        const value = event.target.value as Preference;
        fallback = value;
        try { window.localStorage.setItem(key, value); } catch { /* Session-only preference. */ }
        window.dispatchEvent(new Event(eventName));
      }}
      className="border-input bg-background text-foreground min-h-11 max-w-full rounded-lg border px-2 text-sm"
    >
      <option value="system">{labels.system}</option>
      <option value="light">{labels.light}</option>
      <option value="dark">{labels.dark}</option>
    </select>
  );
}
