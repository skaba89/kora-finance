import Link from "next/link";

import { Button } from "@/components/ui/button";
import { getDictionary } from "@/lib/i18n/server";

export default async function NotFound() {
  const { t } = await getDictionary();
  return (
    <main className="mx-auto flex max-w-md flex-1 flex-col justify-center gap-4 px-4 py-16 text-center">
      <h1 className="text-2xl font-semibold">{t.common.notFoundTitle}</h1>
      <p className="text-muted-foreground">{t.common.notFoundBody}</p>
      <div>
        <Button asChild>
          <Link href="/dossiers">{t.common.backHome}</Link>
        </Button>
      </div>
    </main>
  );
}
