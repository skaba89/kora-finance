"use client";

import { useId, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Building2 } from "lucide-react";
import { Button } from "@/components/ui/button";

type CompanyOption = { id: string; name: string; role: string };

/** Les options proviennent exclusivement de la liste autorisée par l'API. */
export function CompanySwitcher({ companies, currentId, label, openLabel, pendingLabel }: {
  companies: CompanyOption[]; currentId: string; label: string; openLabel: string; pendingLabel: string;
}) {
  const router = useRouter();
  const selectId = useId();
  const [selected, setSelected] = useState(currentId);
  const [pending, startTransition] = useTransition();
  const valid = companies.some(company => company.id === selected);
  return (
    <form className="flex min-w-0 flex-wrap items-center gap-2" onSubmit={event => {
      event.preventDefault();
      if (valid && selected !== currentId) startTransition(() => router.push(`/dossiers/${selected}`));
    }}>
      <Building2 aria-hidden className="text-primary size-5 shrink-0" />
      <label className="sr-only" htmlFor={selectId}>{label}</label>
      <select id={selectId} value={selected} onChange={event => setSelected(event.target.value)} disabled={pending}
        className="bg-background border-input min-h-11 min-w-0 max-w-full flex-1 truncate rounded-lg border px-3 text-sm sm:max-w-72">
        {companies.map(company => <option key={company.id} value={company.id}>{company.name} — {company.role}</option>)}
      </select>
      <Button type="submit" variant="outline" className="min-h-11" disabled={pending || !valid || selected === currentId}>
        {pending ? pendingLabel : openLabel}
      </Button>
    </form>
  );
}
