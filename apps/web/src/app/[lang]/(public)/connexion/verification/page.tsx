import type { Metadata } from "next";
import { Suspense } from "react";

import { ActionForm } from "@/components/forms/action-form";
import { Field } from "@/components/forms/field";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { verifyMfaAction } from "@/lib/actions/auth";
import { getDictionary } from "@/lib/i18n/server";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getDictionary();
  return { title: t.auth.mfaTitle };
}

/** Rendu en un seul bloc avec la destination de retour (voir la page de connexion). */
async function MfaForm({
  searchParams,
}: {
  searchParams: PageProps<"/[lang]/connexion/verification">["searchParams"];
}) {
  const [{ t }, params] = await Promise.all([getDictionary(), searchParams]);
  const next = typeof params.suivant === "string" ? params.suivant : "";
  return (
    <ActionForm action={verifyMfaAction} submitLabel={t.auth.verifyButton} pendingLabel={t.common.pending}>
      <input type="hidden" name="suivant" value={next} />
      <Field
        label={t.auth.code}
        name="code"
        hint={t.auth.codeHint}
        autoComplete="one-time-code"
        inputMode="text"
        required
        autoFocus
      />
    </ActionForm>
  );
}

export default async function MfaPage(props: PageProps<"/[lang]/connexion/verification">) {
  const { t } = await getDictionary();
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h1 className="text-xl">{t.auth.mfaTitle}</h1>
        </CardTitle>
        <CardDescription>{t.auth.mfaSubtitle}</CardDescription>
      </CardHeader>
      <CardContent>
        <Suspense fallback={<div className="bg-muted h-32 animate-pulse rounded" />}>
          <MfaForm searchParams={props.searchParams} />
        </Suspense>
      </CardContent>
    </Card>
  );
}
