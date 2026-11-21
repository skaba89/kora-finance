import Link from "next/link";
import { ArrowUpRight, type LucideIcon } from "lucide-react";
import { Card, CardHeader } from "@/components/ui/card";
import { cn } from "@/lib/utils";

/** Composant de présentation : la valeur est déjà formatée, jamais recalculée ici. */
export function KpiCard({ label, value, hint, href, icon: Icon, negative = false, primary = false }: {
  label: string; value: string; hint?: string; href?: string; icon: LucideIcon;
  negative?: boolean; primary?: boolean;
}) {
  const content = (
    <Card className={cn("h-full min-w-0", primary && "bg-primary/5 ring-primary/30", href && "hover:ring-primary/60 transition-colors")}>
      <CardHeader className="relative min-w-0 gap-2">
        <div aria-hidden className="flex items-center justify-between">
          <span className={cn("bg-muted text-muted-foreground flex size-9 items-center justify-center rounded-lg", primary && "bg-primary/10 text-primary")}>
            <Icon className="size-5" />
          </span>
          {href && <ArrowUpRight className="text-muted-foreground size-4" />}
        </div>
        <p className="text-muted-foreground text-sm font-medium">{label}</p>
        <p className={cn("wrap-anywhere text-2xl font-semibold leading-tight tracking-tight tabular-nums", primary && "text-primary", negative && "text-destructive")}>{value}</p>
        {hint && <p className="text-muted-foreground wrap-anywhere text-xs leading-relaxed">{hint}</p>}
      </CardHeader>
    </Card>
  );
  return href ? <Link href={href} className="block h-full min-w-0 rounded-xl">{content}</Link> : content;
}
