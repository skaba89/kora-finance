import type { ApiClient } from "./client";

export type ApiHealth = "operationnelle" | "degradee" | "injoignable";

/** Interroge la sonde `ready` de l'API et la traduit en état lisible. */
export async function getApiHealth(client: ApiClient): Promise<ApiHealth> {
  try {
    const { data, response } = await client.GET("/health/ready", {
      signal: AbortSignal.timeout(3000),
      cache: "no-store",
    });
    if (response.ok && data?.status === "ok") {
      return "operationnelle";
    }
    // 503 : l'API répond mais une dépendance (base, Redis) est indisponible.
    return response.status === 503 ? "degradee" : "injoignable";
  } catch (error) {
    console.error("Sonde API injoignable", error);
    return "injoignable";
  }
}
