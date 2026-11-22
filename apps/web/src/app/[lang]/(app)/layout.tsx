import Link from "next/link";
import { Suspense } from "react";
import { UserRound } from "lucide-react";

import { FlashProvider } from "@/components/flash/flash-context";
import { InlineAction } from "@/components/forms/inline-action";
import { LocaleSwitcher } from "@/components/locale-switcher";
import { LogoutButton } from "@/components/offline/logout-button";
import { OfflineSync } from "@/components/offline/offline-sync";
import { TopBar } from "@/components/top-bar";
import { SkipLink } from "@/components/skip-link";
import { ThemeSelector } from "@/components/theme-preference";
import { logoutAction, resendVerificationAction } from "@/lib/actions/auth";
import { getCurrentUser } from "@/lib/dal";
import { emailsEnabled } from "@/lib/emails";
import { interpolate } from "@/lib/i18n/interpolate";
import { getDictionary } from "@/lib/i18n/server";

async function UserMenu() {
  const [{ t }, user] = await Promise.all([getDictionary(), getCurrentUser()]);
  return (
    <div className="flex min-w-0 items-center gap-1 sm:gap-3">
      {user.is_platform_admin ? (
        <Link href="/administration" className="hover:bg-accent rounded-lg px-2 py-3 text-sm font-medium">
          Administration
        </Link>
      ) : null}
      <Link href="/compte/securite" className="hover:bg-accent flex min-h-11 min-w-11 max-w-full items-center justify-center gap-2 rounded-lg px-2 text-sm" title={t.nav.security}>
        <UserRound aria-hidden className="text-primary size-5 shrink-0" />
        <span className="sr-only sm:not-sr-only sm:max-w-36 sm:truncate">{user.full_name}</span>
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
      <div className="border-b bg-warning/10 text-warning">
        <p className="mx-auto w-full max-w-[1536px] wrap-anywhere px-4 py-2 text-sm lg:px-8">
          {interpolate(t.auth.unverifiedNoEmail, { email: user.email })}
        </p>
      </div>
    );
  }
  return (
    <div className="border-b bg-warning/10 text-warning">
      <div className="mx-auto flex w-full max-w-[1536px] flex-wrap items-center justify-between gap-2 px-4 py-2 text-sm lg:px-8">
        <p className="min-w-0 wrap-anywhere">{interpolate(t.auth.unverifiedBanner, { email: user.email })}</p>
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
      <SkipLink label={t.common.skipToContent} />
      <TopBar appName={t.common.appName} companiesLabel={t.nav.companies}>
        <ThemeSelector labels={t.theme} />
        <LocaleSwitcher current={locale} label={t.nav.language} />
        <Suspense fallback={<div className="bg-muted h-11 w-28 animate-pulse rounded" />}>
          <UserMenu />
        </Suspense>
      </TopBar>
      <Suspense>
        <UnverifiedEmailBanner />
      </Suspense>
      <Suspense>
        <OfflineSyncSlot />
      </Suspense>
      <div className="mx-auto flex w-full min-w-0 max-w-[1536px] flex-1 flex-col px-4 py-4 md:py-6 lg:px-8">
        <FlashProvider closeLabel={t.common.close}>{children}</FlashProvider>
      </div>
    </div>
  );
}
