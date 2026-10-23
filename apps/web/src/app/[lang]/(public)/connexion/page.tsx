import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { ActionForm } from "@/components/forms/action-form";
import { Field } from "@/components/forms/field";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { loginAction } from "@/lib/actions/auth";
import { getDictionary } from "@/lib/i18n/server";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getDictionary();
  return { title: t.auth.loginTitle };
}

async function Notice({ searchParams }: { searchParams: PageProps<"/[lang]/connexion">["searchParams"] }) {
  const { t } = await getDictionary();
  const params = await searchParams;
  const message = params.inscrit ? t.auth.registered : params.deconnecte ? t.auth.loggedOut : null;
  return message ? (
    <p role="status" className="rounded-md bg-teal-50 px-3 py-2 text-sm text-teal-900">
      {message}
    </p>
  ) : null;
}

async function NextField({ searchParams }: { searchParams: PageProps<"/[lang]/connexion">["searchParams"] }) {
  const value = (await searchParams).suivant;
  return <input type="hidden" name="suivant" value={typeof value === "string" ? value : ""} />;
}

export default async function LoginPage(props: PageProps<"/[lang]/connexion">) {
  const { t } = await getDictionary();
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h1 className="text-xl">{t.auth.loginTitle}</h1>
        </CardTitle>
        <CardDescription>{t.auth.loginSubtitle}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <Suspense>
          <Notice searchParams={props.searchParams} />
        </Suspense>
        <ActionForm action={loginAction} submitLabel={t.auth.loginButton} pendingLabel={t.common.pending}>
          <Suspense>
            <NextField searchParams={props.searchParams} />
          </Suspense>
          <Field label={t.auth.email} name="email" type="email" autoComplete="username" required />
          <Field
            label={t.auth.password}
            name="password"
            type="password"
            autoComplete="current-password"
            required
          />
        </ActionForm>
        <p className="text-muted-foreground text-sm">
          {t.auth.noAccount}{" "}
          <Link href="/inscription" className="text-foreground underline underline-offset-4">
            {t.auth.registerLink}
          </Link>
        </p>
      </CardContent>
    </Card>
  );
}
