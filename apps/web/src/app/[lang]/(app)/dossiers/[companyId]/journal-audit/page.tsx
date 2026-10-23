import type { Metadata } from "next";
import Link from "next/link";

import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { verifyAuditChainAction } from "@/lib/actions/companies";
import { getAuditEvents } from "@/lib/dal";
import { formatDateTime } from "@/lib/format";
import { interpolate } from "@/lib/i18n/interpolate";
import { getDictionary } from "@/lib/i18n/server";

import { AuditVerifier } from "./audit-verifier";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getDictionary();
  return { title: t.audit.title };
}

const PAGE_SIZE = 50;

export default async function AuditPage({
  params,
  searchParams,
}: PageProps<"/[lang]/dossiers/[companyId]/journal-audit">) {
  const { companyId } = await params;
  const raw = (await searchParams).page;
  const page = Math.max(1, Number.parseInt(Array.isArray(raw) ? (raw[0] ?? "1") : (raw ?? "1"), 10) || 1);
  const [{ t, locale }, events] = await Promise.all([
    getDictionary(),
    getAuditEvents(companyId, PAGE_SIZE, (page - 1) * PAGE_SIZE),
  ]);
  const actions: Record<string, string> = t.audit.actions;
  const from = events.total === 0 ? 0 : events.offset + 1;
  const to = events.offset + events.items.length;

  return (
    <>
      <PageHeader
        title={t.audit.title}
        subtitle={t.audit.subtitle}
        actions={
          <AuditVerifier
            action={verifyAuditChainAction.bind(null, companyId)}
            labels={{
              verify: t.audit.verify,
              pending: t.common.pending,
              ok: t.audit.chainOk,
              broken: t.audit.chainBroken,
            }}
          />
        }
      />
      {events.items.length === 0 ? (
        <p className="text-muted-foreground text-sm">{t.audit.empty}</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-14">{t.audit.seq}</TableHead>
              <TableHead className="w-36">{t.audit.date}</TableHead>
              <TableHead>{t.audit.action}</TableHead>
              <TableHead className="hidden lg:table-cell">{t.audit.details}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {events.items.map((event) => (
              <TableRow key={event.seq}>
                <TableCell className="tabular-nums">{event.seq}</TableCell>
                <TableCell>{formatDateTime(event.occurred_at, locale)}</TableCell>
                <TableCell className="whitespace-normal">{actions[event.action] ?? event.action}</TableCell>
                <TableCell className="hidden max-w-md lg:table-cell">
                  <code className="text-muted-foreground line-clamp-2 text-xs break-all">
                    {JSON.stringify(event.payload)}
                  </code>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      <nav className="mt-4 flex items-center justify-between text-sm" aria-label="Pagination">
        <span className="text-muted-foreground">
          {interpolate(t.common.pageRange, { from, to, total: events.total })}
        </span>
        <div className="flex gap-2">
          {page > 1 ? (
            <Button asChild variant="outline" size="sm">
              <Link href={`?page=${page - 1}`}>{t.common.previous}</Link>
            </Button>
          ) : null}
          {to < events.total ? (
            <Button asChild variant="outline" size="sm">
              <Link href={`?page=${page + 1}`}>{t.common.next}</Link>
            </Button>
          ) : null}
        </div>
      </nav>
    </>
  );
}
