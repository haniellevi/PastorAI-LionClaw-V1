import { describe, expect, it } from "vitest";

import {
  broadcastResultFeedback,
  broadcastStatusLabel,
  isSendNowConnectionUnavailable,
  type BroadcastItem,
  type BroadcastResult,
} from "./broadcasts-api";

function result(status: string, enviados = 0): BroadcastResult {
  return {
    id: "broadcast-1",
    status,
    enviados,
    ignoradosOptout: 0,
    agendadoPara: null,
    execucaoId: "execution-1",
    alcancePrevisto: 3,
  };
}

function historyItem(
  overrides: Partial<BroadcastItem> = {},
): BroadcastItem {
  return {
    id: "broadcast-1",
    titulo: "Aviso",
    mensagem: "Mensagem",
    segmentos: ["todos"],
    modo: "agora",
    status: "enviado",
    alcance: 12,
    ignoradosOptout: 0,
    data: null,
    hora: null,
    repeticao: null,
    proximaExecucao: null,
    precisaRevisao: false,
    resultadoUltimaExecucao: null,
    entregasAceitas: 0,
    entregasFalhas: 0,
    entregasDesconhecidas: 0,
    entregasSuprimidas: 0,
    entregasPendentes: 0,
    ...overrides,
  };
}

describe("broadcastResultFeedback", () => {
  it.each(["agendado", "enfileirado", "enviado"])(
    "mantém %s como feedback positivo",
    (status) => {
      expect(broadcastResultFeedback(result(status, 2)).kind).toBe("ok");
    },
  );

  it.each([
    "parcial",
    "falhou",
    "desconhecido",
    "suprimido",
    "concluido_sem_destinatarios",
  ])("nunca apresenta %s como sucesso", (status) => {
    const feedback = broadcastResultFeedback(result(status, 0));
    expect(feedback.kind).toBe("err");
    expect(feedback.text).not.toContain("Comunicado enviado");
  });

  it("orienta não reenviar quando o resultado é desconhecido", () => {
    expect(broadcastResultFeedback(result("desconhecido")).text).toContain(
      "Não reenvie",
    );
  });
});

describe("isSendNowConnectionUnavailable", () => {
  it.each(["offline", "reconectando"] as const)(
    "bloqueia envio imediato quando o WhatsApp está %s",
    (status) => {
      expect(isSendNowConnectionUnavailable(status)).toBe(true);
    },
  );

  it.each(["online", "unknown"] as const)(
    "mantém %s para validação normal do backend",
    (status) => {
      expect(isSendNowConnectionUnavailable(status)).toBe(false);
    },
  );
});

describe("broadcastStatusLabel", () => {
  it("preserva o alcance de comunicados enviados antes do ledger", () => {
    expect(broadcastStatusLabel(historyItem())).toBe("Enviado · 12");
  });

  it("usa as entregas aceitas quando existe resultado do ledger", () => {
    const item = historyItem({
      resultadoUltimaExecucao: "enviado",
      entregasAceitas: 7,
    });

    expect(broadcastStatusLabel(item)).toBe("Enviado · 7");
  });

  it("mantém a recorrência agendada após uma execução concluída", () => {
    const item = historyItem({
      status: "agendado",
      repeticao: "weekly",
      proximaExecucao: "2026-08-12T12:00:00Z",
      resultadoUltimaExecucao: "enviado",
      entregasAceitas: 7,
    });

    expect(broadcastStatusLabel(item)).toBe("Agendado · Semanalmente");
  });
});
