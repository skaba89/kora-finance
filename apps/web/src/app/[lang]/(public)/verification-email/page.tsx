import type { Metadata } from "next";
import { Suspense } from "react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { getDictionary } from "@/lib/i18n/server";

import { MissingLink } from "../missing-link";
import { tokenFrom } from "@/lib/link-token";
import { VerifyEmailForm } from "./verify-email-form";

type Props = PageProps<"/[lang]/verification-email">;

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getDictionary();
  return { title: t.auth.verifyEmailTitle };
}

async function Verification({ searchParams }: { searchParams: Props["searchParams"] }) {
  const [{ t }, params] = await Promise.all([getDictionary(), searchParams]);
  const token = tokenFrom(params);
  if (!token) return <MissingLink t={t} />;
  return (
    <VerifyEmailForm
      token={token}
      labels={{ submit: t.auth.verifyEmailButton, pending: t.common.pending, continue: t.auth.continue }}
    />
  );
}

export default async function VerifyEmailPage(props: Props) {
  const { t } = await getDictionary();
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h1 className="text-xl">{t.auth.verifyEmailTitle}</h1>
        </CardTitle>
        <CardDescription>{t.auth.verifyEmailSubtitle}</CardDescription>
      </CardHeader>
      <CardContent>
        <Suspense fallback={<div className="bg-muted h-24 animate-pulse rounded" />}>
          <Verification searchParams={props.searchParams} />
        </Suspense>
      </CardContent>
    </Card>
  );
}
