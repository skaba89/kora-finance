"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { api, publicApi } from "@/lib/api/server";
import { isLocale } from "@/lib/i18n/config";
import {
  ACCESS_COOKIE,
  cookieOptions,
  LOCALE_COOKIE,
  MFA_COOKIE,
  REFRESH_COOKIE,
  REFRESH_MAX_AGE_SECONDS,
  safeNextPath,
} from "@/lib/session";

import type { ActionState } from "./state";
import { actionDictionary, failure, field } from "./support";

async function storeSession(tokens: { access_token: string; refresh_token: string; expires_in: number }) {
  const store = await cookies();
  store.set(ACCESS_COOKIE, tokens.access_token, cookieOptions(tokens.expires_in));
  store.set(REFRESH_COOKIE, tokens.refresh_token, cookieOptions(REFRESH_MAX_AGE_SECONDS));
  store.delete(MFA_COOKIE);
}

export async function loginAction(_: ActionState, formData: FormData): Promise<ActionState> {
  const next = safeNextPath(field(formData, "suivant"));
  const { data, error } = await (await publicApi()).POST("/api/v1/auth/login", {
    body: { email: field(formData, "email"), password: String(formData.get("password") ?? "") },
  });
  if (!data) return failure(error);
  if (data.status === "mfa_required") {
    (await cookies()).set(MFA_COOKIE, data.mfa_token, cookieOptions(data.expires_in));
    redirect(`/connexion/verification?suivant=${encodeURIComponent(next)}`);
  }
  await storeSession(data);
  redirect(next);
}

export async function verifyMfaAction(_: ActionState, formData: FormData): Promise<ActionState> {
  const store = await cookies();
  const mfaToken = store.get(MFA_COOKIE)?.value;
  if (!mfaToken) {
    const t = await actionDictionary();
    return { status: "error", message: t.auth.mfaExpired };
  }
  const { data, error } = await (await publicApi()).POST("/api/v1/auth/mfa/verify", {
    body: { mfa_token: mfaToken, code: field(formData, "code") },
  });
  if (!data) return failure(error);
  await storeSession(data);
  redirect(safeNextPath(field(formData, "suivant")));
}

export async function registerAction(_: ActionState, formData: FormData): Promise<ActionState> {
  const locale = field(formData, "locale");
  const { error, response } = await (await publicApi()).POST("/api/v1/auth/register", {
    body: {
      email: field(formData, "email"),
      password: String(formData.get("password") ?? ""),
      full_name: field(formData, "full_name"),
      locale: isLocale(locale) ? locale : "fr",
    },
  });
  if (!response.ok) return failure(error);
  redirect("/connexion?inscrit=1");
}

export async function logoutAction(): Promise<void> {
  const store = await cookies();
  const refreshToken = store.get(REFRESH_COOKIE)?.value;
  if (refreshToken) {
    // Échec réseau toléré : les cookies sont supprimés de toute façon.
    await (await publicApi())
      .POST("/api/v1/auth/logout", { body: { refresh_token: refreshToken } })
      .catch((error: unknown) => console.error("Déconnexion API impossible", error));
  }
  store.delete(ACCESS_COOKIE);
  store.delete(REFRESH_COOKIE);
  redirect("/connexion?deconnecte=1");
}

export async function logoutEverywhereAction(): Promise<void> {
  await (await api()).POST("/api/v1/auth/logout-everywhere");
  const store = await cookies();
  store.delete(ACCESS_COOKIE);
  store.delete(REFRESH_COOKIE);
  redirect("/connexion?deconnecte=1");
}

export async function setLocaleAction(formData: FormData): Promise<void> {
  const locale = field(formData, "locale");
  if (isLocale(locale)) {
    (await cookies()).set(LOCALE_COOKIE, locale, {
      ...cookieOptions(365 * 24 * 3600),
      httpOnly: false,
    });
  }
  redirect(safeNextPath(field(formData, "retour")));
}

export async function forgotPasswordAction(_: ActionState, formData: FormData): Promise<ActionState> {
  const { error, response } = await (await publicApi()).POST("/api/v1/auth/password/forgot", {
    body: { email: field(formData, "email") },
  });
  if (!response.ok) return failure(error);
  const t = await actionDictionary();
  return { status: "success", message: t.auth.forgotSent };
}

export async function resetPasswordAction(_: ActionState, formData: FormData): Promise<ActionState> {
  const password = String(formData.get("password") ?? "");
  if (password !== String(formData.get("password_confirm") ?? "")) {
    const t = await actionDictionary();
    return { status: "error", message: t.auth.passwordMismatch };
  }
  const { error, response } = await (await publicApi()).POST("/api/v1/auth/password/reset", {
    body: { token: field(formData, "token"), new_password: password },
  });
  if (!response.ok) return failure(error);
  // Toutes les sessions ont été fermées par l'API, y compris celle de ce navigateur.
  const store = await cookies();
  store.delete(ACCESS_COOKIE);
  store.delete(REFRESH_COOKIE);
  redirect("/connexion?reinitialise=1");
}

export async function verifyEmailAction(_: ActionState, formData: FormData): Promise<ActionState> {
  const { error, response } = await (await publicApi()).POST("/api/v1/auth/email/verify", {
    body: { token: field(formData, "token") },
  });
  if (!response.ok) return failure(error);
  const t = await actionDictionary();
  return { status: "success", message: t.auth.emailVerified };
}

export async function resendVerificationAction(_: ActionState): Promise<ActionState> {
  const { error, response } = await (await api()).POST("/api/v1/auth/email/verification");
  if (!response.ok) return failure(error);
  const t = await actionDictionary();
  return { status: "success", message: t.auth.verificationSent };
}

export async function acceptInvitationAction(_: ActionState, formData: FormData): Promise<ActionState> {
  const { data, error } = await (await publicApi()).POST("/api/v1/invitations/accept", {
    body: {
      token: field(formData, "token"),
      full_name: field(formData, "full_name"),
      password: String(formData.get("password") ?? ""),
    },
  });
  if (!data) return failure(error);
  await storeSession(data);
  redirect(`/dossiers/${data.company_id}`);
}

export async function joinInvitationAction(_: ActionState, formData: FormData): Promise<ActionState> {
  const { data, error } = await (await api()).POST("/api/v1/invitations/join", {
    body: { token: field(formData, "token") },
  });
  if (!data) return failure(error);
  redirect(`/dossiers/${data.company_id}`);
}
