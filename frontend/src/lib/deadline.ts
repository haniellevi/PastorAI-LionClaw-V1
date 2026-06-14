/**
 * Lógica do deadline-badge (selo de prazo) — SPEC componente `deadline-badge`.
 * Estados: dentro (ok) -> alerta (warn) -> atrasado (late). A transição é
 * derivada apenas do prazo vs. "agora"; o painel recalcula a cada tick (sem
 * reload), o que faz o selo migrar de estado e reordena a fila por urgência.
 */

export type DeadlineTone = "ok" | "warn" | "late" | "none";

/** Janela de alerta: dentro deste intervalo o selo vira "alerta". */
export const WARN_WINDOW_MS = 24 * 60 * 60 * 1000; // 24h

export interface DeadlineInfo {
  tone: DeadlineTone;
  /** Rótulo curto, ex.: "faltam 9h", "atrasado 6h", "vence em 2 dias". */
  label: string;
  /** Estado textual para acessibilidade/estados do componente. */
  state: "dentro" | "alerta" | "atrasado" | "sem-prazo";
}

function humanize(ms: number): string {
  const totalMin = Math.round(ms / 60000);
  if (totalMin < 60) {
    const m = Math.max(1, totalMin);
    return `${m} min`;
  }
  const totalHours = Math.round(totalMin / 60);
  if (totalHours < 48) {
    return `${totalHours}h`;
  }
  const days = Math.round(totalHours / 24);
  return `${days} dia${days > 1 ? "s" : ""}`;
}

/**
 * Calcula o estado do prazo para um instante `now`.
 * Passar `now` explicitamente mantém o cálculo puro/testável e permite ao
 * painel forçar recálculo periódico.
 */
export function computeDeadline(prazoIso: string | null, now: number = Date.now()): DeadlineInfo {
  if (!prazoIso) {
    return { tone: "none", label: "", state: "sem-prazo" };
  }
  const prazo = Date.parse(prazoIso);
  if (Number.isNaN(prazo)) {
    return { tone: "none", label: "", state: "sem-prazo" };
  }

  const diff = prazo - now;
  if (diff < 0) {
    return { tone: "late", label: `atrasado ${humanize(-diff)}`, state: "atrasado" };
  }
  if (diff <= WARN_WINDOW_MS) {
    return { tone: "warn", label: `faltam ${humanize(diff)}`, state: "alerta" };
  }
  return { tone: "ok", label: `vence em ${humanize(diff)}`, state: "dentro" };
}

/** Peso de severidade para ordenação (menor = mais urgente). */
const TONE_WEIGHT: Record<DeadlineTone, number> = {
  late: 0,
  warn: 1,
  ok: 2,
  none: 3,
};

/**
 * Comparador de urgência: ordena por severidade do prazo, depois pelo prazo
 * mais próximo e por fim pela prioridade declarada do item (menor primeiro).
 */
export function compareUrgency(
  a: { prazo: string | null; prioridade: number | null },
  b: { prazo: string | null; prioridade: number | null },
  now: number = Date.now(),
): number {
  const da = computeDeadline(a.prazo, now);
  const db = computeDeadline(b.prazo, now);
  const wa = TONE_WEIGHT[da.tone];
  const wb = TONE_WEIGHT[db.tone];
  if (wa !== wb) return wa - wb;

  // Mesma severidade: prazo mais próximo primeiro.
  const pa = a.prazo ? Date.parse(a.prazo) : Number.POSITIVE_INFINITY;
  const pb = b.prazo ? Date.parse(b.prazo) : Number.POSITIVE_INFINITY;
  if (pa !== pb) return pa - pb;

  // Desempate por prioridade declarada (nulos por último).
  const ra = a.prioridade ?? Number.POSITIVE_INFINITY;
  const rb = b.prioridade ?? Number.POSITIVE_INFINITY;
  return ra - rb;
}
