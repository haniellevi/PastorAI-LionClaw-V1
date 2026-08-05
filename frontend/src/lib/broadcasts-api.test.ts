import { describe, expect, it } from "vitest";

import {
  broadcastResultFeedback,
  isSendNowConnectionUnavailable,
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
