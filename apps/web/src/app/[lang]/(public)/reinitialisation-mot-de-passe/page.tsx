import type { Metadata } from "next";
import { Suspense } from "react";

import { ActionForm } from "@/components/forms/action-form";
import { Field } from "@/components/forms/field";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { resetPasswordAction } from "@/lib/actions/auth";
import { getDictionary } from "@/lib/i18n/server";

import { MissingLink } from "../missing-link";
import { tokenFrom } from "@/lib/link-token";

type Props = PageProps<"/[lang]/reinitialisation-mot-de-passe">;

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getDictionary();
  return { title: t.auth.resetTitle };
}

/** Rendu en un seul bloc avec le jeton : le formulaire ne part jamais sans lui. */
async function ResetForm({ searchParams }: { searchParams: Props["searchParams"] }) {
  const [{ t }, params] = await Promise.all([getDictionary(), searchParams]);
  const token = tokenFrom(params);
  if (!token) return <MissingLink t={t} retryHref="/mot-de-passe-oublie" />;
  return (
    <ActionForm action={resetPasswordAction} submitLabel={t.auth.resetButton} pendingLabel={t.common.pending}>
      <input type="hidden" name="token" value={token} />
      <Field
        label={t.security.newPassword}
        name="password"
        type="password"
        autoComplete="new-password"
        hint={t.auth.passwordHint}
        minLength={10}
        required
      />
      <Field
        label={t.auth.confirmPassword}
        name="password_confirm"
        type="password"
        autoComplete="new-password"
        minLength={10}
        required
      />
    </ActionForm>
  );
}

export default async function ResetPasswordPage(props: Props) {
  const { t } = await getDictionary();
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h1 className="text-xl">{t.auth.resetTitle}</h1>
        </CardTitle>
        <CardDescription>{t.auth.resetSubtitle}</CardDescription>
      </CardHeader>
      <CardContent>
        <Suspense fallback={<div className="bg-muted h-48 animate-pulse rounded" />}>
          <ResetForm searchParams={props.searchParams} />
        </Suspense>
      </CardContent>
    </Card>
  );
}
