import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { EmailsDisabledNotice } from "@/components/emails-disabled-notice";
import { ActionForm } from "@/components/forms/action-form";
import { Field } from "@/components/forms/field";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { forgotPasswordAction } from "@/lib/actions/auth";
import { getDictionary } from "@/lib/i18n/server";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getDictionary();
  return { title: t.auth.forgotTitle };
}

export default async function ForgotPasswordPage() {
  const { t } = await getDictionary();
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h1 className="text-xl">{t.auth.forgotTitle}</h1>
        </CardTitle>
        <CardDescription>{t.auth.forgotSubtitle}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <Suspense fallback={null}>
          <EmailsDisabledNotice message={t.auth.emailsDisabled} />
        </Suspense>
        <ActionForm action={forgotPasswordAction} submitLabel={t.auth.forgotButton} pendingLabel={t.common.pending}>
          <Field label={t.auth.email} name="email" type="email" autoComplete="username" required />
        </ActionForm>
        <Link href="/connexion" className="text-sm underline underline-offset-4">
          {t.auth.backToLogin}
        </Link>
      </CardContent>
    </Card>
  );
}
