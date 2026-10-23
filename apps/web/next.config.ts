import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Image Docker minimale : seul le serveur autonome est copié dans l'image finale.
  output: "standalone",
  poweredByHeader: false,
  async headers() {
    return [
      {
        // Le service worker doit toujours être revalidé pour que les mises à jour arrivent.
        source: "/sw.js",
        headers: [
          { key: "Content-Type", value: "application/javascript; charset=utf-8" },
          { key: "Cache-Control", value: "no-cache, no-store, must-revalidate" },
          { key: "Content-Security-Policy", value: "default-src 'self'; script-src 'self'" },
        ],
      },
    ];
  },
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
