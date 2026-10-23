/*
 * Service worker Kora Finance (phase 1 : installation PWA et page hors connexion).
 *
 * Les pages authentifiées ne sont JAMAIS mises en cache : elles contiennent des
 * données comptables confidentielles. Seule la page « hors connexion » est préchargée
 * et servie quand une navigation échoue faute de réseau. La saisie hors-ligne avec
 * synchronisation arrive en phase 2.
 */
const CACHE = "kora-shell-v1";
const OFFLINE_URL = "/hors-connexion";

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      .then((cache) => cache.add(new Request(OFFLINE_URL, { cache: "reload" })))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  if (event.request.mode !== "navigate") return;
  event.respondWith(
    fetch(event.request).catch(async () => {
      const cache = await caches.open(CACHE);
      return (await cache.match(OFFLINE_URL)) ?? Response.error();
    }),
  );
});
