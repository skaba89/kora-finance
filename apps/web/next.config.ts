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
  experimental: {
    serverActions: {
      // Pièces justificatives (10 Mo au plus côté API) envoyées par Server Action.
      bodySizeLimit: "11mb",
      // Preview bac à sable uniquement : la passerelle de la plateforme
      // réécrit `x-forwarded-host` ; autoriser les origines du chat
      // (ne jamais reproduire en production).
      allowedOrigins: ["*.space-z.ai", "preview-chat-6ba03784-73a3-4747-a1a6-4c134eb9d19e.space-z.ai"],
    },
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
