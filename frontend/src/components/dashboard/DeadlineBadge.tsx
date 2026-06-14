/**
 * deadline-badge — selo de prazo (dentro/alerta/atrasado).
 * Recebe o `prazo` (ISO) e o instante `now` do painel; a transição de estado
 * acontece sem reload conforme `now` avança (o painel fornece o tick).
 */
import { Icon } from "@/lib/icons";
import { computeDeadline } from "@/lib/deadline";

const TONE_CLASS = {
  ok: "",
  warn: "warn",
  late: "late",
  none: "",
} as const;

export function DeadlineBadge({
  prazo,
  now,
  prefix,
}: {
  prazo: string | null;
  now: number;
  /** Prefixo opcional, ex.: "prazo 24h", "fonovisita". */
  prefix?: string;
}) {
  const info = computeDeadline(prazo, now);
  if (info.tone === "none") return null;

  const label = prefix ? `${prefix} · ${info.label}` : info.label;

  return (
    <span
      className={`ddl ${TONE_CLASS[info.tone]}`.trim()}
      data-state={info.state}
      role="status"
    >
      <Icon name="clock" />
      {label}
    </span>
  );
}
