import type { Metadata } from "next";
import Link from "next/link";

import { ActionForm } from "@/components/forms/action-form";
import { Field } from "@/components/forms/field";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { registerAction } from "@/lib/actions/auth";
import { getDictionary } from "@/lib/i18n/server";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getDictionary();
  return { title: t.auth.registerTitle };
}

export default async function RegisterPage() {
  const { t, locale } = await getDictionary();
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h1 className="text-xl">{t.auth.registerTitle}</h1>
        </CardTitle>
        <CardDescription>{t.auth.registerSubtitle}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <ActionForm action={registerAction} submitLabel={t.auth.registerButton} pendingLabel={t.common.pending}>
          <input type="hidden" name="locale" value={locale} />
          <Field label={t.auth.fullName} name="full_name" autoComplete="name" required maxLength={200} />
          <Field label={t.auth.email} name="email" type="email" autoComplete="email" required />
          <Field
            label={t.auth.password}
            name="password"
            type="password"
            autoComplete="new-password"
            hint={t.auth.passwordHint}
            minLength={10}
            required
          />
        </ActionForm>
        <p className="text-muted-foreground text-sm">
          {t.auth.haveAccount}{" "}
          <Link href="/connexion" className="text-foreground underline underline-offset-4">
            {t.auth.loginLink}
          </Link>
        </p>
      </CardContent>
    </Card>
  );
}
