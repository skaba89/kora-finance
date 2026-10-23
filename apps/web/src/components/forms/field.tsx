import type { ComponentProps, ReactNode } from "react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

type Props = ComponentProps<typeof Input> & {
  label: string;
  name: string;
  hint?: ReactNode;
};

/** Champ libellé, accessible (label associé, aide reliée par aria-describedby). */
export function Field({ label, name, hint, id, ...input }: Props) {
  const inputId = id ?? `champ-${name}`;
  const hintId = hint ? `${inputId}-aide` : undefined;
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={inputId}>{label}</Label>
      <Input id={inputId} name={name} aria-describedby={hintId} {...input} />
      {hint ? (
        <p id={hintId} className="text-muted-foreground text-xs">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

type SelectProps = ComponentProps<"select"> & {
  label: string;
  name: string;
  options: { value: string; label: string }[];
};

/** Liste déroulante native : légère et utilisable sur tous les téléphones. */
export function SelectField({ label, name, options, id, className, ...select }: SelectProps) {
  const selectId = id ?? `champ-${name}`;
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={selectId}>{label}</Label>
      <select
        id={selectId}
        name={name}
        className={
          className ??
          "border-input bg-background h-9 rounded-md border px-3 text-sm shadow-xs focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none"
        }
        {...select}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  );
}
