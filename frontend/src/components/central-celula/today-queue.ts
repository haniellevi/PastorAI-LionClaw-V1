import type { CellHealth, PendingReportItem } from "@/lib/cell-central-api";
import type { CellRequest } from "@/lib/cell-requests-api";
import type { MultiplicacaoPendente } from "@/lib/multiplicacoes-api";

import type { CentralTab } from "./types";

export type TodayKind = "report" | "request" | "multiplication" | "health";

export interface TodayItem {
  id: string;
  kind: TodayKind;
  title: string;
  meta: string;
  action: string;
  goTo: CentralTab;
  sortAt: number;
}

const REQUEST_LABELS: Record<string, string> = {
  alterar_dia: "Alterar dia",
  alterar_horario: "Alterar horário",
  alterar_endereco: "Alterar endereço",
  alterar_anfitriao: "Alterar anfitrião",
  alterar_auxiliar: "Alterar auxiliar",
  transferir_membro: "Transferir membro",
  remover_membro: "Remover membro",
  multiplicacao: "Multiplicação",
};

const KIND_WEIGHT: Record<TodayKind, number> = {
  report: 0,
  request: 1,
  multiplication: 2,
  health: 3,
};

export function requestTypeLabel(tipo: string): string {
  return REQUEST_LABELS[tipo] ?? tipo;
}

export function healthNeedsAttention(cell: CellHealth): boolean {
  return cell.status === "critico" || cell.status === "atencao" || cell.vermelhos > 0 || cell.alertas > 0;
}

export function healthStatusLabel(cell: CellHealth): string {
  if (cell.status === "critico" || cell.vermelhos > 1) return "Crítica";
  if (cell.status === "atencao" || cell.alertas > 0 || cell.vermelhos > 0) return "Atenção";
  return "Saudável";
}

function stamp(value: string | null | undefined): number {
  if (!value) return Number.POSITIVE_INFINITY;
  const parsed = Date.parse(value.length === 10 ? `${value}T12:00:00` : value);
  return Number.isNaN(parsed) ? Number.POSITIVE_INFINITY : parsed;
}

export function buildTodayQueue(input: {
  reports: readonly PendingReportItem[];
  requests: readonly CellRequest[];
  multiplications: readonly MultiplicacaoPendente[];
  health: readonly CellHealth[];
}): TodayItem[] {
  const items: TodayItem[] = input.reports.map((report) => ({
    id: `report:${report.reuniao_id}`,
    kind: "report",
    title: `Relatório pendente · ${report.celula_nome}`,
    meta: `${report.lider_nome} · reunião em ${report.data}`,
    action: "Ver relatórios",
    goTo: "cells",
    sortAt: stamp(report.data),
  }));

  for (const request of input.requests) {
    if (request.tipo === "multiplicacao") continue;
    items.push({
      id: `request:${request.id}`,
      kind: "request",
      title: requestTypeLabel(request.tipo),
      meta: request.created_at ?? "Aguardando decisão",
      action: "Decidir",
      goTo: "requests",
      sortAt: stamp(request.created_at),
    });
  }

  for (const multiplication of input.multiplications) {
    items.push({
      id: `mult:${multiplication.id}`,
      kind: "multiplication",
      title: "Multiplicação aguardando",
      meta: multiplication.created_at ?? "Aguardando decisão",
      action: "Decidir",
      goTo: "requests",
      sortAt: stamp(multiplication.created_at),
    });
  }

  for (const cell of input.health) {
    if (!healthNeedsAttention(cell)) continue;
    items.push({
      id: `health:${cell.celula_id}`,
      kind: "health",
      title: `${cell.celula_nome} precisa de cuidado`,
      meta: `${healthStatusLabel(cell)} · ${cell.vermelhos} vermelho(s), ${cell.alertas} alerta(s)`,
      action: "Ver saúde",
      goTo: "cells",
      sortAt: stamp(null),
    });
  }

  return items.sort((a, b) => {
    const byKind = KIND_WEIGHT[a.kind] - KIND_WEIGHT[b.kind];
    if (byKind !== 0) return byKind;
    return a.sortAt - b.sortAt;
  });
}
