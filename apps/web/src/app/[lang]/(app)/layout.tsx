import Link from "next/link";
import { Suspense } from "react";

import { InlineAction } from "@/components/forms/inline-action";
import { LocaleSwitcher } from "@/components/locale-switcher";
import { Button } from "@/components/ui/button";
import { logoutAction, resendVerificationAction } from "@/lib/actions/auth";
import { getCurrentUser } from "@/lib/dal";
import { interpolate } from "@/lib/i18n/interpolate";
import { getDictionary } from "@/lib/i18n/server";

async function UserMenu() {
  const [{ t }, user] = await Promise.all([getDictionary(), getCurrentUser()]);
  return (
    <div className="flex items-center gap-3">
      <Link href="/compte/securite" className="hidden text-sm sm:inline" title={t.nav.security}>
        {user.full_name}
      </Link>
      <form action={logoutAction}>
        <Button type="submit" variant="outline" size="sm">
          {t.nav.logout}
        </Button>
      </form>
    </div>
  );
}

/** Rappel tant que l'adresse n'est pas confirmée (condition pour inviter quelqu'un). */
async function UnverifiedEmailBanner() {
  const [{ t }, user] = await Promise.all([getDictionary(), getCurrentUser()]);
  if (user.email_verified) return null;
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
      <header className="border-b">
        <div className="mx-auto flex w-full max-w-6xl items-center justify-between gap-4 px-4 py-3">
          <Link href="/dossiers" className="font-semibold tracking-tight text-teal-700">
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
      <div className="mx-auto flex w-full max-w-6xl flex-1 flex-col px-4 py-6">{children}</div>
    </div>
  );
}
