import { Wifi, WifiOff } from "lucide-react";

import type { Dictionary } from "@/lib/i18n/server";
import { cn } from "@/lib/utils";

/** Browser connectivity only: not a guarantee that the server is reachable. */
export function NetworkIndicator({ online, labels }: { online: boolean; labels: Dictionary["offline"] }) {
  const Icon = online ? Wifi : WifiOff;
  return (
    <p role="status" className={cn("inline-flex w-fit items-center gap-2 rounded-full border px-3 py-1.5 text-sm font-medium", online ? "bg-success/10 text-success" : "bg-warning/10 text-warning")}>
      <Icon aria-hidden="true" className="size-4" />
      {online ? labels.networkOnline : labels.networkOffline}
    </p>
  );
}
