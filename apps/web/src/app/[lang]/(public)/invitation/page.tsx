import type { Metadata } from "next";
import { cookies } from "next/headers";
import Link from "next/link";
import { Suspense } from "react";

import { ActionForm } from "@/components/forms/action-form";
import { Field } from "@/components/forms/field";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { acceptInvitationAction, joinInvitationAction, logoutAction } from "@/lib/actions/auth";
import { publicApi, toApiError } from "@/lib/api/server";
import { getCurrentUser } from "@/lib/dal";
import { interpolate } from "@/lib/i18n/interpolate";
import { getDictionary } from "@/lib/i18n/server";
import { ACCESS_COOKIE } from "@/lib/session";

import { MissingLink } from "../missing-link";
import { tokenFrom } from "@/lib/link-token";

type Props = PageProps<"/[lang]/invitation">;

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getDictionary();
  return { title: t.invitation.title };
}

async function InvitationContent({ searchParams }: { searchParams: Props["searchParams"] }) {
  const [{ t }, params] = await Promise.all([getDictionary(), searchParams]);
  const token = tokenFrom(params);
  if (!token) return <MissingLink t={t} />;

  // Consultation seule : afficher la page ne consomme pas l'invitation.
  const { data: invitation, error } = await (await publicApi()).POST("/api/v1/invitations/preview", {
    body: { token },
  });
  if (!invitation) {
    return (
      <Alert variant="destructive" role="alert">
        <AlertDescription>{toApiError(error, t.common.unexpectedError).detail}</AlertDescription>
      </Alert>
    );
  }

  const summary = (
    <div className="flex flex-col gap-1">
      <p>
        {interpolate(t.invitation.summary, {
          inviter: invitation.inviter_name,
          company: invitation.company_name,
          role: t.roles[invitation.role],
        })}
      </p>
      <p className="text-muted-foreground text-sm">
        {interpolate(t.invitation.invitedAddress, { email: invitation.email })}
      </p>
    </div>
  );

  if (!invitation.account_exists) {
    return (
      <div className="flex flex-col gap-4">
        {summary}
        <p className="text-sm">{t.invitation.createAccount}</p>
        <ActionForm action={acceptInvitationAction} submitLabel={t.invitation.acceptButton} pendingLabel={t.common.pending}>
          <input type="hidden" name="token" value={token} />
          <Field label={t.auth.fullName} name="full_name" autoComplete="name" required maxLength={200} />
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
      </div>
    );
  }

  const signedIn = (await cookies()).has(ACCESS_COOKIE);
  if (!signedIn) {
    const back = `/invitation?jeton=${token}`;
    return (
      <div className="flex flex-col gap-4">
        {summary}
        <p className="text-sm">{t.invitation.existingAccount}</p>
        <div>
          <Button asChild>
            <Link href={`/connexion?suivant=${encodeURIComponent(back)}`}>{t.invitation.loginToAccept}</Link>
          </Button>
        </div>
      </div>
    );
  }

  const user = await getCurrentUser();
  if (user.email !== invitation.email) {
    return (
      <div className="flex flex-col gap-4">
        {summary}
        <Alert role="alert">
          <AlertDescription>{interpolate(t.invitation.wrongAccount, { email: user.email })}</AlertDescription>
        </Alert>
        <form action={logoutAction}>
          <Button type="submit" variant="outline">
            {t.nav.logout}
          </Button>
        </form>
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-4">
      {summary}
      <ActionForm action={joinInvitationAction} submitLabel={t.invitation.joinButton} pendingLabel={t.common.pending}>
        <input type="hidden" name="token" value={token} />
      </ActionForm>
    </div>
  );
}

export default async function InvitationPage(props: Props) {
  const { t } = await getDictionary();
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h1 className="text-xl">{t.invitation.title}</h1>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <Suspense fallback={<div className="bg-muted h-48 animate-pulse rounded" />}>
          <InvitationContent searchParams={props.searchParams} />
        </Suspense>
      </CardContent>
    </Card>
  );
}
