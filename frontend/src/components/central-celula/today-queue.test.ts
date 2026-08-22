import { describe, expect, it } from "vitest";

import type { CellHealth, PendingReportItem } from "@/lib/cell-central-api";
import type { CellRequest } from "@/lib/cell-requests-api";
import type { MultiplicacaoPendente } from "@/lib/multiplicacoes-api";

import { buildTodayQueue, countActionableItems, healthNeedsAttention } from "./today-queue";

function report(partial: Partial<PendingReportItem> = {}): PendingReportItem {
  return {
    reuniao_id: "r1",
    celula_id: "c1",
    celula_nome: "Célula Vida",
    lider_nome: "João Pereira",
    data: "2026-08-10",
    ...partial,
  };
}

function request(partial: Partial<CellRequest> = {}): CellRequest {
  return {
    id: "q1",
    celula_id: "c1",
    solicitante_id: null,
    pessoa_id: null,
    tipo: "alterar_horario",
    status: "aguardando",
    payload_proposto: {},
    payload_atual: null,
    motivo: null,
    observacao_central: null,
    decidido_por: null,
    decidido_em: null,
    created_at: "2026-08-11T12:00:00Z",
    updated_at: null,
    ...partial,
  };
}

function multiplication(partial: Partial<MultiplicacaoPendente> = {}): MultiplicacaoPendente {
  return {
    id: "m1",
    celula_id: "c1",
    solicitante_id: null,
    tipo: "multiplicacao",
    status: "aguardando",
    payload_proposto: {},
    created_at: "2026-08-12T09:00:00Z",
    ...partial,
  };
}

function health(partial: Partial<CellHealth> = {}): CellHealth {
  return {
    celula_id: "c2",
    celula_nome: "Célula Esperança",
    status: "atencao",
    sinais: [],
    vermelhos: 0,
    alertas: 1,
    ...partial,
  };
}

describe("buildTodayQueue", () => {
  it("monta a fila por pessoa e prazo, sem repetir multiplicação", () => {
    const items = buildTodayQueue({
      reports: [report()],
      requests: [request(), request({ id: "q2", tipo: "multiplicacao" })],
      multiplications: [multiplication()],
      health: [health(), health({ celula_id: "c3", status: "saudavel", alertas: 0, vermelhos: 0 })],
    });

    expect(items.map((item) => item.id)).toEqual([
      "report:r1",
      "request:q1",
      "mult:m1",
      "health:c2",
    ]);
    expect(items[0]?.title).toContain("Célula Vida");
    expect(items[1]?.goTo).toBe("requests");
    expect(items[2]?.goTo).toBe("requests");
    expect(items[3]?.action).toBe("Ver saúde");
  });

  it("fica vazia quando não há exceção", () => {
    expect(
      buildTodayQueue({
        reports: [],
        requests: [],
        multiplications: [],
        health: [health({ status: "saudavel", vermelhos: 0, alertas: 0 })],
      }),
    ).toEqual([]);
  });
});

describe("countActionableItems", () => {
  it("não conta multiplicações duas vezes dentro das solicitações", () => {
    expect(
      countActionableItems({
        relatorios_pendentes: 2,
        solicitacoes_aguardando: 3,
        celulas_com_alerta: 1,
        multiplicacoes_pendentes: 2,
        avisos_recentes: 4,
        materiais_recentes: 5,
      }),
    ).toBe(6);
  });
});

describe("healthNeedsAttention", () => {
  it("ignora célula saudável sem sinais", () => {
    expect(healthNeedsAttention(health({ status: "saudavel", vermelhos: 0, alertas: 0 }))).toBe(
      false,
    );
  });
});
