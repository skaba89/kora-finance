/*
 * Service worker Kora Finance : installation PWA, page hors connexion et page de
 * saisie hors connexion.
 *
 * Les pages authentifiées ne sont JAMAIS mises en cache : elles contiennent des
 * données comptables confidentielles. Seules deux pages publiques et statiques sont
 * conservées (« hors connexion » et « saisie hors connexion », sans aucune donnée), avec
 * les fichiers de l'application qu'elles utilisent (/_next/static, publics et immuables).
 * Les données d'un dossier pour saisir hors connexion vivent dans IndexedDB, chiffrées,
 * gérées par l'application (jamais par ce fichier).
 */
const SHELL = "kora-shell-v2";
const ASSETS = "kora-assets-v1";
const OFFLINE_URL = "/hors-connexion";
const ENTRY_URL = "/hors-connexion/saisie";
const STATIC_PREFIX = "/_next/static/";
const STATIC_REFERENCE = /\/_next\/static\/[^"'\\\s)<>]+/g;

/** Page publique + fichiers statiques qu'elle référence (y compris dans les données RSC). */
async function fetchShell(cache) {
  for (const url of [OFFLINE_URL, ENTRY_URL]) {
    const response = await fetch(new Request(url, { cache: "reload", credentials: "same-origin" }));
    if (!response.ok || response.redirected) throw new Error(`Page ${url} indisponible (${response.status})`);
    const html = await response.clone().text();
    await cache.put(url, response);
    const assets = [...new Set(html.match(STATIC_REFERENCE) ?? [])];
    await Promise.all(
      assets.map(async (asset) => {
        if (await cache.match(asset)) return;
        const file = await fetch(asset, { credentials: "same-origin" });
        if (file.ok) await cache.put(asset, file);
      }),
    );
  }
}

/** Nouvelle version de l'application : on reconstitue les pages hors ligne à part, puis on remplace. */
async function refreshShell() {
  const name = `${SHELL}-next`;
  await caches.delete(name);
  const fresh = await caches.open(name);
  await fetchShell(fresh);
  const current = await caches.open(SHELL);
  for (const request of await current.keys()) await current.delete(request);
  for (const request of await fresh.keys()) await current.put(request, await fresh.match(request));
  await caches.delete(name);
  // Fichiers d'anciennes versions : la page à jour référence les siens (dans SHELL).
  await caches.delete(ASSETS);
}

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(SHELL)
      .then(fetchShell)
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== SHELL && key !== ASSETS).map((key) => caches.delete(key))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("message", (event) => {
  if (event.data && event.data.type === "refresh-offline-shell") {
    event.waitUntil(refreshShell().catch((error) => console.error("Pages hors connexion non mises à jour", error)));
  }
});

async function cachedPage(url) {
  const cache = await caches.open(SHELL);
  return (await cache.match(url)) ?? Response.error();
}

async function staticAsset(request) {
  const cached = (await caches.match(request)) ?? null;
  if (cached) return cached;
  const response = await fetch(request);
  if (response.ok) {
    const cache = await caches.open(ASSETS);
    await cache.put(request, response.clone());
  }
  return response;
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (request.mode === "navigate") {
    const entry = url.pathname === ENTRY_URL || /^\/(fr|en)\/hors-connexion\/saisie$/.test(url.pathname);
    event.respondWith(fetch(request).catch(() => cachedPage(entry ? ENTRY_URL : OFFLINE_URL)));
    return;
  }
  // Fichiers de build (noms contenant une empreinte : immuables, publics).
  if (url.pathname.startsWith(STATIC_PREFIX)) event.respondWith(staticAsset(request));
});
