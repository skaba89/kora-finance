import react from "@vitejs/plugin-react";
import tsconfigPaths from "vite-tsconfig-paths";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [tsconfigPaths(), react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    // `server-only` lève une erreur hors d'un bundle serveur : neutralisé en test unitaire.
    alias: { "server-only": new URL("./src/test/empty-module.ts", import.meta.url).pathname },
  },
});
