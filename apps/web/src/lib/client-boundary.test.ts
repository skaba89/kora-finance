import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * Garde-fou de la frontière serveur/client (régression de la page licences) :
 * un module "use client" ne peut fournir au serveur que des composants. Une
 * fonction (nom en minuscule) importée par un fichier serveur fait échouer le
 * rendu (« Attempted to call … from the server »), sans que Vitest ni l'E2E
 * des non-admins ne le voient.
 */
const SRC = join(__dirname, "..");

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sourceFiles(path);
    return /\.(ts|tsx)$/.test(name) && !/\.test\.tsx?$/.test(name) ? [path] : [];
  });
}

function isClientModule(path: string): boolean {
  return /^\s*["']use client["']/.test(readFileSync(path, "utf8"));
}

function resolveAlias(specifier: string): string | null {
  if (!specifier.startsWith("@/")) return null;
  const base = join(SRC, specifier.slice(2));
  for (const candidate of [`${base}.ts`, `${base}.tsx`, join(base, "index.ts"), join(base, "index.tsx")]) {
    if (existsSync(candidate)) return candidate;
  }
  return null;
}

describe("frontière serveur/client", () => {
  it("aucun fichier serveur n'importe une fonction d'un module \"use client\"", { timeout: 30_000 }, () => {
    const violations: string[] = [];
    for (const file of sourceFiles(SRC)) {
      if (isClientModule(file)) continue;
      const code = readFileSync(file, "utf8");
      for (const match of code.matchAll(/^import\s+(type\s+)?\{([^}]*)\}\s+from\s+["']([^"']+)["']/gm)) {
        if (match[1]) continue;
        const target = resolveAlias(match[3] ?? "");
        if (!target || !isClientModule(target)) continue;
        const names = (match[2] ?? "")
          .split(",")
          .map((part) => part.trim())
          .filter((part) => part && !part.startsWith("type "))
          .map((part) => part.split(/\s+as\s+/)[0]?.trim() ?? "");
        for (const name of names) {
          // Composants (PascalCase) et constantes (MAJUSCULES) sont sérialisables ou rendus.
          if (/^[a-z]/.test(name)) violations.push(`${relative(SRC, file)} → ${name} (${match[3]})`);
        }
      }
    }
    expect(violations).toEqual([]);
  });
});
