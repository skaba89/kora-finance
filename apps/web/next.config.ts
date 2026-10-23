import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Image Docker minimale : seul le serveur autonome est copié dans l'image finale.
  output: "standalone",
  poweredByHeader: false,
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
