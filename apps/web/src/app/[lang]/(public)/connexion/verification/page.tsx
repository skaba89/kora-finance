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

async function NextField({
  searchParams,
}: {
  searchParams: PageProps<"/[lang]/connexion/verification">["searchParams"];
}) {
  const value = (await searchParams).suivant;
  return <input type="hidden" name="suivant" value={typeof value === "string" ? value : ""} />;
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
        <ActionForm action={verifyMfaAction} submitLabel={t.auth.verifyButton} pendingLabel={t.common.pending}>
          <Suspense>
            <NextField searchParams={props.searchParams} />
          </Suspense>
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
      </CardContent>
    </Card>
  );
}
