import Link from "next/link";
import { Suspense } from "react";

import { LocaleSwitcher } from "@/components/locale-switcher";
import { Button } from "@/components/ui/button";
import { logoutAction } from "@/lib/actions/auth";
import { getCurrentUser } from "@/lib/dal";
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
      <div className="mx-auto flex w-full max-w-6xl flex-1 flex-col px-4 py-6">{children}</div>
    </div>
  );
}
