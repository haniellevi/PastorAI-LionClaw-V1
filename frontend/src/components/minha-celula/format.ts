/**
 * Formatadores de data/hora da Minha Célula (pt-BR, sem dependências).
 * Reaproveita formatLongDate (events-api) para datas ISO (YYYY-MM-DD) e
 * acrescenta helpers próprios para timestamps ISO-8601 (publicado_em).
 */
import { formatLongDate } from "@/lib/events-api";

export { formatLongDate };

const WEEKDAYS = [
  "domingo",
  "segunda-feira",
  "terça-feira",
  "quarta-feira",
  "quinta-feira",
  "sexta-feira",
  "sábado",
] as const;

/** Dia da semana (pt-BR) de uma data ISO "YYYY-MM-DD", ou string vazia. */
export function weekdayOf(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  if (!y || !m || !d) return "";
  // Meio-dia local evita saltos de fuso na conversão.
  const date = new Date(y, m - 1, d, 12, 0, 0);
  return WEEKDAYS[date.getDay()] ?? "";
}

/** "quarta-feira, 8 de julho de 2026" — data por extenso com dia da semana. */
export function formatMeetingDate(iso: string): string {
  const wd = weekdayOf(iso);
  const long = formatLongDate(iso);
  return wd ? `${wd}, ${long}` : long;
}

/** "8 de julho de 2026 · 20:15" — timestamp ISO-8601 de publicação. */
export function formatPublishedAt(iso: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const day = date.getDate();
  const month = MONTH_NAMES[date.getMonth()] ?? "";
  const year = date.getFullYear();
  const hh = String(date.getHours()).padStart(2, "0");
  const mm = String(date.getMinutes()).padStart(2, "0");
  return `${day} de ${month} de ${year} · ${hh}:${mm}`;
}

const MONTH_NAMES = [
  "janeiro",
  "fevereiro",
  "março",
  "abril",
  "maio",
  "junho",
  "julho",
  "agosto",
  "setembro",
  "outubro",
  "novembro",
  "dezembro",
] as const;
