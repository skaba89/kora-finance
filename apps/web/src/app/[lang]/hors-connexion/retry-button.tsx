"use client";

import { useEffect } from "react";

import { Button } from "@/components/ui/button";

export function RetryButton({ label }: { label: string }) {
  useEffect(() => {
    const reload = () => window.location.reload();
    window.addEventListener("online", reload);
    return () => window.removeEventListener("online", reload);
  }, []);
  return (
    <div>
      <Button onClick={() => window.location.reload()}>{label}</Button>
    </div>
  );
}
