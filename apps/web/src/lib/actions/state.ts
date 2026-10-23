/** État renvoyé par une Server Action à son formulaire (useActionState). */
export type ActionState = {
  status: "idle" | "success" | "error";
  message?: string;
  errors?: string[];
  /** Données à afficher une seule fois (ex. codes de secours 2FA). */
  data?: Record<string, unknown>;
};

export const IDLE: ActionState = { status: "idle" };
