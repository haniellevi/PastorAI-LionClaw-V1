// @vitest-environment jsdom
/**
 * Gate 7 (Onda 4A): regressão do item da fila pastoral — a repaginação visual
 * NÃO pode mudar o conjunto de ações nem a ação principal de cada tipo:
 *  - visitante/conectar_celula → principal "Conectar à célula";
 *  - fonovisita → principal "Fonovisita" (semântica intacta — mesmo callback);
 *  - atendimento/relatorio → principal "Assumir";
 *  - Assumir/Atribuir/Mensagem presentes em TODOS os tipos;
 *  - assumido → "Assumido" desabilitado; busy → tudo desabilitado.
 *
 * Sem JSX (createElement): o tsconfig do Next usa jsx:"preserve".
 */
import { act, createElement as h } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { WorkItem } from "@/lib/dashboard-api";

import { WorkQueueItem } from "./WorkQueueItem";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const baseItem = (over: Partial<WorkItem>): WorkItem => ({
  id: "q1",
  tipo: "visitante",
  titulo: "Conectar Ana Souza a uma célula",
  contexto: "Nova pessoa",
  status: "pendente",
  pessoaId: "p1",
  responsavelId: null,
  prioridade: 1,
  prazo: new Date(Date.now() + 3600e3).toISOString(),
  ...over,
});

const noop = () => {};
const callbacks = {
  onAssume: noop,
  onAssign: noop,
  onMessage: noop,
  onLinkCell: noop,
  onFonovisita: noop,
};

let container: HTMLDivElement;
let root: Root;

function render(item: WorkItem, extra: Record<string, unknown> = {}) {
  act(() => {
    root.render(
      h(WorkQueueItem, {
        item,
        now: Date.now(),
        responsibleName: null,
        ...callbacks,
        ...extra,
      }),
    );
  });
}

/** Botões da linha por rótulo → { primary, disabled }. */
function buttons(): Map<string, { primary: boolean; disabled: boolean }> {
  const map = new Map<string, { primary: boolean; disabled: boolean }>();
  container.querySelectorAll<HTMLButtonElement>(".dh-item-actions button").forEach((b) => {
    map.set(b.textContent!.trim(), {
      primary: b.classList.contains("ds-btn--primary"),
      disabled: b.disabled,
    });
  });
  return map;
}

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe("WorkQueueItem — ação principal por tipo (Gate 7)", () => {
  it("visitante/conectar_celula: 'Conectar à célula' primária + Assumir/Atribuir/Mensagem presentes", () => {
    for (const tipo of ["visitante", "conectar_celula"]) {
      render(baseItem({ tipo }));
      const b = buttons();
      expect([...b.keys()]).toEqual(["Conectar à célula", "Assumir", "Atribuir", "Mensagem"]);
      expect(b.get("Conectar à célula")!.primary).toBe(true);
      expect(b.get("Assumir")!.primary).toBe(false);
    }
  });

  it("fonovisita: 'Fonovisita' primária, sem perder Assumir/Atribuir/Mensagem", () => {
    render(baseItem({ tipo: "fonovisita" }));
    const b = buttons();
    expect([...b.keys()]).toEqual(["Fonovisita", "Assumir", "Atribuir", "Mensagem"]);
    expect(b.get("Fonovisita")!.primary).toBe(true);
  });

  it("atendimento/relatorio: 'Assumir' primária", () => {
    for (const tipo of ["atendimento", "relatorio"]) {
      render(baseItem({ tipo }));
      const b = buttons();
      expect([...b.keys()]).toEqual(["Assumir", "Atribuir", "Mensagem"]);
      expect(b.get("Assumir")!.primary).toBe(true);
    }
  });

  it("assumido: botão vira 'Assumido' e fica desabilitado; demais seguem ativos", () => {
    render(baseItem({ tipo: "atendimento", status: "assumido" }));
    const b = buttons();
    expect(b.get("Assumido")!.disabled).toBe(true);
    expect(b.get("Atribuir")!.disabled).toBe(false);
    expect(b.get("Mensagem")!.disabled).toBe(false);
  });

  it("busy: todas as ações desabilitadas", () => {
    render(baseItem({ tipo: "visitante" }), { busy: true });
    for (const [, meta] of buttons()) expect(meta.disabled).toBe(true);
  });

  it("callbacks preservados: clique dispara o handler correto", () => {
    const onLinkCell = vi.fn();
    const onFonovisita = vi.fn();
    render(baseItem({ tipo: "conectar_celula" }), { onLinkCell });
    act(() => {
      [...container.querySelectorAll("button")]
        .find((b) => b.textContent!.includes("Conectar à célula"))!
        .click();
    });
    expect(onLinkCell).toHaveBeenCalledTimes(1);

    render(baseItem({ tipo: "fonovisita" }), { onFonovisita });
    act(() => {
      [...container.querySelectorAll("button")]
        .find((b) => b.textContent!.includes("Fonovisita"))!
        .click();
    });
    expect(onFonovisita).toHaveBeenCalledTimes(1);
  });

  it("conflito de concorrência renderiza com role=alert", () => {
    render(baseItem({ tipo: "relatorio" }), { conflict: "Já tratado por Ana Lima" });
    const alert = container.querySelector('[role="alert"]');
    expect(alert?.textContent).toContain("Já tratado por Ana Lima");
  });
});
