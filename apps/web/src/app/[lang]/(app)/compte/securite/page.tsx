import type { Metadata } from "next";
import { Suspense } from "react";
import { KeyRound, ShieldCheck, ShieldAlert, Monitor } from "lucide-react";

import { ActionForm } from "@/components/forms/action-form";
import { Field } from "@/components/forms/field";
import { PageHeader, PageSkeleton } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { logoutEverywhereAction } from "@/lib/actions/auth";
import { changePasswordAction } from "@/lib/actions/security";
import { getCurrentUser } from "@/lib/dal";
import { getDictionary } from "@/lib/i18n/server";

import { MfaManager } from "./mfa-manager";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getDictionary();
  return { title: t.security.title };
}

async function SecurityContent() {
  const [{ t }, user] = await Promise.all([getDictionary(), getCurrentUser()]);
  return (
    <div className="flex max-w-3xl min-w-0 flex-col gap-6">
      <PageHeader title={t.security.title} subtitle={`${user.full_name} · ${user.email}`} />

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base"><KeyRound aria-hidden className="size-5 text-primary" />{t.security.passwordTitle}</CardTitle>
        </CardHeader>
        <CardContent>
          <ActionForm
            action={changePasswordAction}
            submitLabel={t.security.changePassword}
            pendingLabel={t.common.pending}
            resetOnSuccess
          >
            <Field
              label={t.security.currentPassword}
              name="current_password"
              type="password"
              autoComplete="current-password"
              required
            />
            <Field
              label={t.security.newPassword}
              name="new_password"
              type="password"
              autoComplete="new-password"
              minLength={10}
              hint={t.auth.passwordHint}
              required
            />
          </ActionForm>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">{user.mfa_enabled ? <ShieldCheck aria-hidden className="size-5 text-success" /> : <ShieldAlert aria-hidden className="size-5 text-muted-foreground" />}{t.security.mfaTitle}</CardTitle>
          <CardDescription className={user.mfa_enabled ? "font-medium text-success" : undefined}>{user.mfa_enabled ? t.security.mfaOn : t.security.mfaOff}</CardDescription>
        </CardHeader>
        <CardContent>
          <MfaManager
            enabled={user.mfa_enabled}
            labels={{
              start: t.security.mfaStart,
              scan: t.security.mfaScan,
              secret: t.security.mfaSecret,
              confirm: t.security.mfaConfirm,
              code: t.auth.code,
              password: t.auth.password,
              passwordHint: t.security.mfaPasswordHint,
              recoveryTitle: t.security.recoveryTitle,
              recoveryNotice: t.security.recoveryNotice,
              disable: t.security.mfaDisable,
              regenerate: t.security.mfaRegenerate,
              reauth: t.security.mfaReauth,
              pending: t.common.pending,
            }}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base"><Monitor aria-hidden className="size-5 text-primary" />{t.security.sessionsTitle}</CardTitle>
          <CardDescription>{t.security.logoutEverywhereHint}</CardDescription>
        </CardHeader>
        <CardContent>
          <form action={logoutEverywhereAction}>
            <Button type="submit" variant="outline" className="min-h-11 whitespace-normal">
              {t.security.logoutEverywhere}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}

export default function SecurityPage() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <SecurityContent />
    </Suspense>
  );
}
