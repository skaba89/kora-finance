import { LocaleSwitcher } from "@/components/locale-switcher";
import { SkipLink } from "@/components/skip-link";
import { getDictionary } from "@/lib/i18n/server";

export default async function PublicLayout({ children }: LayoutProps<"/[lang]">) {
  const { t, locale } = await getDictionary();
  return (
    <div className="flex flex-1 flex-col">
      <SkipLink label={t.common.skipToContent} />
      <header className="flex items-center justify-between px-4 py-3">
        <span className="font-semibold tracking-tight text-primary">{t.common.appName}</span>
        <LocaleSwitcher current={locale} label={t.nav.language} />
      </header>
      <main id="main-content" tabIndex={-1} className="flex flex-1 items-start justify-center px-4 py-8 sm:items-center">
        <div className="w-full max-w-sm">{children}</div>
      </main>
    </div>
  );
}
