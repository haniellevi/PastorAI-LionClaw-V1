/**
 * CONV-AI-1: coerência "sem interesse" ⇒ "IA pausada" nas derivações puras do
 * inbox. Um contato sem interesse NUNCA pode ser rotulado "IA ativa" — o worker
 * do backend já suprime a resposta automática (inclusive p/ legado estado="ia").
 * O fluxo normal (sem interesse=false) permanece inalterado.
 */
import { describe, expect, it } from "vitest";

import type { Conversation } from "@/lib/conversations-api";

import {
  conversationPill,
  effectiveEstado,
  estadoPill,
  iaPausadaSemInteresse,
} from "./conversation-format";

const conv = (over: Partial<Conversation>): Conversation => ({
  id: "c1",
  telefone: "5511987654321",
  pessoaId: "p1",
  nome: "Ana Souza",
  estado: "ia",
  ultimaMensagem: "Bom dia!",
  naoLidas: 0,
  assumidoPor: null,
  assumidoPorNome: null,
  assumidoEm: null,
  esperaDesde: null,
  atualizadoEm: null,
  tipo: "contato",
  semInteresse: false,
  ...over,
});

describe("conversation-format — IA pausada por sem interesse (CONV-AI-1)", () => {
  it("contato normal (estado ia) não está pausado e mostra 'IA ativa'", () => {
    const c = conv({ semInteresse: false, estado: "ia" });
    expect(iaPausadaSemInteresse(c)).toBe(false);
    expect(conversationPill(c)).toEqual(estadoPill("ia"));
    expect(conversationPill(c).label).toBe("IA ativa");
  });

  it("sem interesse + estado ia ⇒ pausado e 'IA pausada' (nunca 'IA ativa')", () => {
    const c = conv({ semInteresse: true, estado: "ia" });
    expect(iaPausadaSemInteresse(c)).toBe(true);
    expect(conversationPill(c)).toEqual({ tone: "muted", label: "IA pausada" });
    expect(conversationPill(c).label).not.toBe("IA ativa");
  });

  it("legado: sem interesse + estado ia + espera_desde setado ainda é 'IA pausada'", () => {
    // Registro inconsistente (o antigo "aguardando") não pode reabilitar a IA.
    const c = conv({
      semInteresse: true,
      estado: "ia",
      esperaDesde: "2026-07-14T12:00:00Z",
    });
    expect(effectiveEstado(c)).toBe("aguardando");
    expect(iaPausadaSemInteresse(c)).toBe(true);
    expect(conversationPill(c).label).toBe("IA pausada");
  });

  it("humano tem prioridade: sem interesse + estado humano ⇒ 'Em atendimento'", () => {
    const c = conv({ semInteresse: true, estado: "humano", assumidoPor: "u1" });
    expect(iaPausadaSemInteresse(c)).toBe(false);
    expect(conversationPill(c).label).toBe("Em atendimento");
  });

  it("fluxo normal 'aguardando' (sem interesse=false) permanece inalterado", () => {
    const c = conv({ semInteresse: false, estado: "aguardando" });
    expect(iaPausadaSemInteresse(c)).toBe(false);
    expect(conversationPill(c)).toEqual(estadoPill("aguardando"));
    expect(conversationPill(c).label).toBe("Aguardando humano");
  });

  it("configuração global inativa substitui 'IA ativa' por 'IA pausada pela igreja'", () => {
    const c = conv({ semInteresse: false, estado: "ia" });
    expect(conversationPill(c, "paused_by_church")).toEqual({
      tone: "muted",
      label: "IA pausada pela igreja",
    });
    expect(conversationPill(c, "paused_by_church").label).not.toBe("IA ativa");
  });

  it("falha na leitura global não presume que a IA está ativa", () => {
    const c = conv({ semInteresse: false, estado: "ia" });
    expect(conversationPill(c, "unknown")).toEqual({
      tone: "warn",
      label: "Estado da IA indisponível",
    });
  });

  it("controle humano e fila de espera continuam prioritários ao estado global", () => {
    expect(
      conversationPill(
        conv({ estado: "humano", assumidoPor: "u1" }),
        "paused_by_church",
      ).label,
    ).toBe("Em atendimento");
    expect(
      conversationPill(conv({ estado: "aguardando" }), "paused_by_church").label,
    ).toBe("Aguardando humano");
  });
});
