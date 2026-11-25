// Test de charge k6 : journée type en LECTURE SEULE sur le dossier de démonstration.
// Aucune écriture : pas d'effet comptable, rejouable à volonté (`make load`).
// Prérequis : pile démarrée (`make up`) et démonstration chargée (`make seed`).
//
// Seuils = objectifs de service initiaux, à confirmer sur la cible de production
// (le poste local ne représente pas le VPS) : < 1 % d'erreurs, p95 < 800 ms et
// p99 < 2 s sur l'ensemble, p95 < 1,5 s sur les états financiers (agrégats lourds).
import http from "k6/http";
import { check, fail, group, sleep } from "k6";

const API = __ENV.KORA_LOAD_API_URL || "http://api:8000";
const PASSWORD = __ENV.KORA_LOAD_PASSWORD || "KoraDemo2026!";
const USERS = ["directeur@demo.kora.gn", "comptable@demo.kora.gn", "lecteur@demo.kora.gn"];

export const options = {
  scenarios: {
    journee: {
      executor: "ramping-vus",
      startVUs: 0,
      stages: [
        { duration: "30s", target: Number(__ENV.KORA_LOAD_VUS || 20) },
        { duration: __ENV.KORA_LOAD_DURATION || "2m", target: Number(__ENV.KORA_LOAD_VUS || 20) },
        { duration: "15s", target: 0 },
      ],
      gracefulRampDown: "10s",
    },
  },
  thresholds: {
    http_req_failed: ["rate<0.01"],
    http_req_duration: ["p(95)<800", "p(99)<2000"],
    "http_req_duration{lourd:oui}": ["p(95)<1500"],
    checks: ["rate>0.99"],
  },
};

function getJson(path, token, tags = {}) {
  const response = http.get(`${API}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
    tags: { route: path.replace(/[0-9a-f-]{36}/g, "{id}").split("?")[0], ...tags },
  });
  check(response, { [`${response.request.method} 200`]: (r) => r.status === 200 });
  return response.status === 200 ? response.json() : null;
}

// Connexion une seule fois par compte : la limitation de débit de /auth/login
// n'est pas l'objet de ce test (elle est couverte par les tests d'intégration).
export function setup() {
  return USERS.map((email) => {
    const login = http.post(`${API}/api/v1/auth/login`, JSON.stringify({ email, password: PASSWORD }), {
      headers: { "Content-Type": "application/json" },
    });
    if (login.status !== 200 || !login.json("access_token")) {
      fail(`Connexion impossible pour ${email} (${login.status}) : lancer \`make seed\` d'abord.`);
    }
    const token = login.json("access_token");
    const companies = getJson("/api/v1/companies", token);
    const access = (companies || []).find((item) => item.company.legal_name.startsWith("Djouma"));
    if (!access) fail(`Dossier de démonstration absent pour ${email}.`);
    const companyId = access.company.id;
    const years = getJson(`/api/v1/companies/${companyId}/fiscal-years`, token) || [];
    if (years.length === 0) fail("Aucun exercice dans le dossier de démonstration.");
    return { token, companyId, fiscalYearId: years[0].id };
  });
}

export default function (sessions) {
  const { token, companyId, fiscalYearId } = sessions[(__VU - 1) % sessions.length];
  const base = `/api/v1/companies/${companyId}`;
  group("tableau de bord", () => {
    getJson("/api/v1/companies", token);
    getJson(`${base}/dashboard`, token);
  });
  sleep(1);
  group("écritures", () => {
    getJson(`${base}/entries?limit=50`, token);
  });
  sleep(1);
  group("états", () => {
    getJson(`${base}/trial-balance?fiscal_year_id=${fiscalYearId}`, token, { lourd: "oui" });
    getJson(`${base}/financial-statements?fiscal_year_id=${fiscalYearId}`, token, { lourd: "oui" });
  });
  sleep(1);
  group("ventes", () => {
    getJson(`${base}/sales?limit=50`, token);
  });
  sleep(2);
}

// Le jeton d'accès dure 15 min : la durée totale par défaut (moins de 3 min) reste
// en deçà. Pour un essai plus long, relancer plutôt que d'allonger KORA_LOAD_DURATION.
