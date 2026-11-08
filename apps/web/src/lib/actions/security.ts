"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { api } from "@/lib/api/server";
import { ACCESS_COOKIE, cookieOptions, REFRESH_COOKIE, REFRESH_MAX_AGE_SECONDS } from "@/lib/session";

import type { ActionState } from "./state";
import { actionDictionary, failure, field } from "./support";

export async function changePasswordAction(_: ActionState, formData: FormData): Promise<ActionState> {
  const { data, error } = await (await api()).POST("/api/v1/auth/password", {
    body: {
      current_password: String(formData.get("current_password") ?? ""),
      new_password: String(formData.get("new_password") ?? ""),
    },
  });
  if (!data) return failure(error);
  // Les autres sessions sont fermées ; celle-ci reçoit de nouveaux jetons.
  const store = await cookies();
  store.set(ACCESS_COOKIE, data.access_token, cookieOptions(data.expires_in));
  store.set(REFRESH_COOKIE, data.refresh_token, cookieOptions(REFRESH_MAX_AGE_SECONDS));
  const t = await actionDictionary();
  return { status: "success", message: t.security.passwordChanged };
}

export async function startMfaSetupAction(_: ActionState, formData: FormData): Promise<ActionState> {
  // L'enrôlement exige la réauthentification : le mot de passe est vérifié par l'API
  // (un seul jeton d'accès ne suffit plus à installer un second facteur, KF-08).
  const { data, error } = await (await api()).POST("/api/v1/auth/mfa/setup", {
    body: { password: String(formData.get("password") ?? "") },
  });
  if (!data) return failure(error);
  return { status: "success", data };
}

export async function enableMfaAction(_: ActionState, formData: FormData): Promise<ActionState> {
  const { data, error } = await (await api()).POST("/api/v1/auth/mfa/enable", {
    body: {
      password: String(formData.get("password") ?? ""),
      code: field(formData, "code"),
    },
  });
  if (!data) return failure(error);
  // Pas de refresh() : la page passerait en mode « activé » et masquerait les codes de
  // secours avant que l'utilisateur ait pu les noter.
  return { status: "success", data };
}

export async function disableMfaAction(_: ActionState, formData: FormData): Promise<ActionState> {
  const { error, response } = await (await api()).POST("/api/v1/auth/mfa/disable", {
    body: { password: String(formData.get("password") ?? ""), code: field(formData, "code") },
  });
  if (!response.ok) return failure(error);
  // Désactiver la 2FA ferme toutes les sessions, y compris celle-ci.
  const store = await cookies();
  store.delete(ACCESS_COOKIE);
  store.delete(REFRESH_COOKIE);
  redirect("/connexion?deconnecte=1");
}

export async function regenerateRecoveryCodesAction(
  _: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const { data, error } = await (await api()).POST("/api/v1/auth/mfa/recovery-codes", {
    body: { password: String(formData.get("password") ?? ""), code: field(formData, "code") },
  });
  if (!data) return failure(error);
  return { status: "success", data };
}
