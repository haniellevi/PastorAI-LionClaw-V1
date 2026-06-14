/**
 * status-pill — pílula de status (tone: ok|warn|danger|accent|muted).
 * Espelha o componente travado no artifact (.pill + variantes).
 */
import type { ReactNode } from "react";

export type PillTone = "ok" | "warn" | "danger" | "accent" | "muted";

export function StatusPill({
  tone = "muted",
  children,
}: {
  tone?: PillTone;
  children: ReactNode;
}) {
  return <span className={`pill ${tone}`}>{children}</span>;
}
