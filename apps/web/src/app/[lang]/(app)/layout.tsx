import Link from "next/link";
import { Suspense } from "react";

import { FlashProvider } from "@/components/flash/flash-context";
import { InlineAction } from "@/components/forms/inline-action";
import { LocaleSwitcher } from "@/components/locale-switcher";
import { LogoutButton } from "@/components/offline/logout-button";
import { OfflineSync } from "@/components/offline/offline-sync";
import { logoutAction, resendVerificationAction } from "@/lib/actions/auth";
import { getCurrentUser } from "@/lib/dal";
import { emailsEnabled } from "@/lib/emails";
import { interpolate } from "@/lib/i18n/interpolate";
import { getDictionary } from "@/lib/i18n/server";

async function UserMenu() {
  const [{ t }, user] = await Promise.all([getDictionary(), getCurrentUser()]);
  return (
    <div className="flex items-center gap-3">
      <Link href="/compte/securite" className="hidden text-sm sm:inline" title={t.nav.security}>
        {user.full_name}
      </Link>
      <LogoutButton action={logoutAction} userId={user.id} label={t.nav.logout} confirmTemplate={t.offline.logoutConfirm} />
    </div>
  );
}

/** Envoi des saisies faites hors connexion et bandeau de suivi. */
async function OfflineSyncSlot() {
  const [{ t }, user] = await Promise.all([getDictionary(), getCurrentUser()]);
  return <OfflineSync userId={user.id} labels={t.offline} />;
}

/** Rappel tant que l'adresse n'est pas confirmée (condition pour inviter quelqu'un). */
async function UnverifiedEmailBanner() {
  const [{ t }, user, canSend] = await Promise.all([getDictionary(), getCurrentUser(), emailsEnabled()]);
  if (user.email_verified) return null;
  if (!canSend) {
    return (
      <div className="border-b bg-amber-50 text-amber-950">
        <p className="mx-auto w-full max-w-6xl px-4 py-2 text-sm">
          {interpolate(t.auth.unverifiedNoEmail, { email: user.email })}
        </p>
      </div>
    );
  }
  return (
    <div className="border-b bg-amber-50 text-amber-950">
      <div className="mx-auto flex w-full max-w-6xl flex-wrap items-center justify-between gap-2 px-4 py-2 text-sm">
        <p>{interpolate(t.auth.unverifiedBanner, { email: user.email })}</p>
        <InlineAction
          action={resendVerificationAction}
          label={t.auth.resendVerification}
          pendingLabel={t.common.pending}
          showSuccess
        />
      </div>
    </div>
  );
}

export default async function AppLayout({ children }: LayoutProps<"/[lang]">) {
  const { t, locale } = await getDictionary();
  return (
    <div className="flex flex-1 flex-col">
      <header className="border-b bg-card">
        <div className="mx-auto flex w-full max-w-[1536px] flex-wrap items-center justify-between gap-3 px-4 py-3 lg:px-8">
          <Link href="/dossiers" className="font-semibold tracking-tight text-primary">
            {t.common.appName}
          </Link>
          <div className="flex items-center gap-4">
            <LocaleSwitcher current={locale} label={t.nav.language} />
            <Suspense fallback={<div className="bg-muted h-8 w-28 animate-pulse rounded" />}>
              <UserMenu />
            </Suspense>
          </div>
        </div>
      </header>
      <Suspense>
        <UnverifiedEmailBanner />
      </Suspense>
      <Suspense>
        <OfflineSyncSlot />
      </Suspense>
      <div className="mx-auto flex w-full min-w-0 max-w-[1536px] flex-1 flex-col px-4 py-6 lg:px-8">
        <FlashProvider closeLabel={t.common.close}>{children}</FlashProvider>
      </div>
    </div>
  );
}
