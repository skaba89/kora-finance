"use client";

import { useActionState } from "react";

import { ActionForm } from "@/components/forms/action-form";
import { Field } from "@/components/forms/field";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import type { ActionState } from "@/lib/actions/state";
import {
  disableMfaAction,
  enableMfaAction,
  regenerateRecoveryCodesAction,
  startMfaSetupAction,
} from "@/lib/actions/security";

type Labels = {
  start: string;
  scan: string;
  secret: string;
  confirm: string;
  code: string;
  password: string;
  passwordHint: string;
  recoveryTitle: string;
  recoveryNotice: string;
  disable: string;
  regenerate: string;
  reauth: string;
  pending: string;
};

const IDLE: ActionState = { status: "idle" };

function RecoveryCodes({ state, labels }: { state: ActionState; labels: Labels }) {
  const codes = state.data?.recovery_codes;
  if (state.status !== "success" || !Array.isArray(codes)) return null;
  return (
    <div className="rounded-md border border-amber-300 bg-amber-50 p-4 text-amber-950">
      <p className="font-medium">{labels.recoveryTitle}</p>
      <p className="mt-1 text-sm">{labels.recoveryNotice}</p>
      <ul className="mt-3 grid grid-cols-2 gap-2 font-mono text-sm">
        {codes.map((code) => (
          <li key={String(code)}>{String(code)}</li>
        ))}
      </ul>
    </div>
  );
}

function ReauthFields({ labels }: { labels: Labels }) {
  return (
    <>
      <p className="text-muted-foreground text-sm">{labels.reauth}</p>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={labels.password} name="password" type="password" autoComplete="current-password" required />
        <Field label={labels.code} name="code" autoComplete="one-time-code" required />
      </div>
    </>
  );
}

export function MfaManager({ enabled, labels }: { enabled: boolean; labels: Labels }) {
  const [setup, startSetup, starting] = useActionState(startMfaSetupAction, IDLE);

  if (enabled) {
    return (
      <div className="flex flex-col gap-6">
        <ActionForm
          action={regenerateRecoveryCodesAction}
          submitLabel={labels.regenerate}
          pendingLabel={labels.pending}
          variant="outline"
          renderResult={(state) => <RecoveryCodes state={state} labels={labels} />}
        >
          <ReauthFields labels={labels} />
        </ActionForm>
        <ActionForm action={disableMfaAction} submitLabel={labels.disable} pendingLabel={labels.pending} variant="destructive">
          <ReauthFields labels={labels} />
        </ActionForm>
      </div>
    );
  }

  const data = setup.status === "success" ? setup.data : undefined;
  if (!data) {
    return (
      <form action={startSetup} className="flex flex-col gap-4">
        <p className="text-muted-foreground text-sm">{labels.reauth}</p>
        <Field
          label={labels.password}
          name="password"
          type="password"
          autoComplete="current-password"
          hint={labels.passwordHint}
          required
        />
        {setup.status === "error" && setup.message ? (
          <Alert variant="destructive" role="alert">
            <AlertDescription>
              <p>{setup.message}</p>
            </AlertDescription>
          </Alert>
        ) : null}
        <div>
          <Button type="submit" disabled={starting}>
            {starting ? labels.pending : labels.start}
          </Button>
        </div>
      </form>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm">{labels.scan}</p>
      {/* QR code SVG produit par l'API (data URI) : aucune requête externe. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={String(data.qr_svg_data_uri)} alt="QR code" width={200} height={200} className="rounded border bg-white p-2" />
      <p className="text-sm">
        {labels.secret} <code className="bg-muted rounded px-1 font-mono text-xs break-all">{String(data.secret)}</code>
      </p>
      <ActionForm
        action={enableMfaAction}
        submitLabel={labels.confirm}
        pendingLabel={labels.pending}
        renderResult={(state) => <RecoveryCodes state={state} labels={labels} />}
      >
        <Field
          label={labels.password}
          name="password"
          type="password"
          autoComplete="current-password"
          hint={labels.passwordHint}
          required
        />
        <Field label={labels.code} name="code" autoComplete="one-time-code" inputMode="numeric" required />
      </ActionForm>
    </div>
  );
}
