// @vitest-environment jsdom
/**
 * W4A — ReportDetailModal migrado para o DsDialog (somente-leitura). Cobre o
 * shell acessível do primitive: abertura, os três caminhos de fechamento
 * (botão Fechar, backdrop, Esc), foco inicial, retorno de foco ao gatilho e
 * focus trap. Sem `busy`: fechar nunca é bloqueado.
 *
 * Harness sem @testing-library (não instalada no repo): createRoot + act,
 * espelhando frontend/src/components/ds/Dialog.test.ts.
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getFocusable } from "@/components/ds/a11y";
import type { ReportItem } from "@/lib/reports-api";

import { ReportDetailModal } from "./ReportDetailModal";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

const report: ReportItem = {
  id: "r1",
  celulaId: "c1",
  celulaNome: "Célula Zoe",
  semana: "2026-W29",
  status: "recebido",
  dataReuniao: "2026-07-15",
  presentes: 12,
  visitantes: 2,
  decisoes: 1,
  oferta: 50,
  observacoes: "Tudo certo.",
};

beforeEach(() => {
  // jsdom não implementa layout: offsetParent nulo quebra o filtro de
  // visibilidade do getFocusable — apontamos para o pai direto.
  Object.defineProperty(HTMLElement.prototype, "offsetParent", {
    configurable: true,
    get(this: HTMLElement) {
      return this.parentElement;
    },
  });
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

function panel(): HTMLElement {
  const el = container.querySelector<HTMLElement>('[role="dialog"]');
  if (!el) throw new Error("dialog não encontrado");
  return el;
}
function overlay(): HTMLElement {
  const el = container.querySelector<HTMLElement>(".ds-overlay");
  if (!el) throw new Error("overlay não encontrado");
  return el;
}
function closeButton(): HTMLElement {
  const el = container.querySelector<HTMLElement>('[aria-label="Fechar"]');
  if (!el) throw new Error("botão Fechar não encontrado");
  return el;
}
function pressKey(key: string, shiftKey = false) {
  act(() => {
    document.dispatchEvent(new KeyboardEvent("keydown", { key, shiftKey, bubbles: true }));
  });
}
function fire(el: Element, type: "click" | "mousedown") {
  act(() => {
    el.dispatchEvent(new MouseEvent(type, { bubbles: true }));
  });
}
function renderModal(onClose: () => void, item: ReportItem = report) {
  act(() => {
    root.render(<ReportDetailModal report={item} onClose={onClose} />);
  });
}

describe("ReportDetailModal — DsDialog acessível (somente-leitura)", () => {
  it("abre como dialog modal com o título do relatório", () => {
    renderModal(vi.fn());
    expect(panel().getAttribute("aria-modal")).toBe("true");
    expect(container.textContent).toContain("Relatório — Célula Zoe");
  });

  it("fecha pelo botão Fechar", () => {
    const onClose = vi.fn();
    renderModal(onClose);
    fire(closeButton(), "click");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("fecha por clique no overlay (backdrop)", () => {
    const onClose = vi.fn();
    renderModal(onClose);
    fire(overlay(), "mousedown");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("fecha por Esc", () => {
    const onClose = vi.fn();
    renderModal(onClose);
    pressKey("Escape");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("foco inicial vai para o primeiro focável (botão Fechar do cabeçalho)", () => {
    renderModal(vi.fn());
    expect(document.activeElement?.getAttribute("aria-label")).toBe("Fechar");
  });

  it("retorna o foco ao elemento que abriu quando fecha", () => {
    const opener = document.createElement("button");
    document.body.appendChild(opener);
    opener.focus();
    expect(document.activeElement).toBe(opener);

    renderModal(vi.fn());
    expect(document.activeElement).not.toBe(opener);

    act(() => root.render(null)); // o pai reage fechando (desmonta o modal)
    expect(document.activeElement).toBe(opener);
    opener.remove();
  });

  it("Tab é interceptado pelo focus trap (não escapa do diálogo)", () => {
    renderModal(vi.fn());
    const focusables = getFocusable(panel());
    focusables[focusables.length - 1]!.focus();
    // Este modal somente-leitura tem um único focável (o botão Fechar), então o
    // foco não "anda" no Tab; o que prova o trap é o preventDefault do handler —
    // sem ele o Tab nativo escaparia (jsdom não implementa navegação de Tab).
    const tab = new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true });
    act(() => {
      document.dispatchEvent(tab);
    });
    expect(tab.defaultPrevented).toBe(true);
    expect(panel().contains(document.activeElement)).toBe(true);
  });
});

describe("ReportDetailModal — contrato honesto (REPORT-SOT-IMPLEMENT-1)", () => {
  it("NÃO exibe origem falsa: sem rótulo 'Origem' e sem 'WhatsApp'", () => {
    renderModal(vi.fn());
    const text = container.textContent ?? "";
    expect(text).not.toContain("WhatsApp");
    expect(text).not.toContain("Origem");
  });

  it("recebido mostra os números reais do snapshot e a data da reunião", () => {
    renderModal(vi.fn());
    const text = container.textContent ?? "";
    expect(text).toContain("Recebido");
    expect(text).toContain("Presentes");
    expect(text).toContain("12");
    expect(text).toContain("15/07/2026");
  });

  it("pendente não inventa números e aponta o painel, não o WhatsApp", () => {
    renderModal(vi.fn(), {
      ...report,
      status: "pendente",
      presentes: null,
      visitantes: null,
      decisoes: null,
      oferta: null,
      observacoes: null,
    });
    const text = container.textContent ?? "";
    expect(text).toContain("Pendente");
    expect(text).toContain("Relatório ainda não enviado.");
    expect(text).toContain("Minha Célula");
    expect(text).not.toContain("WhatsApp");
    expect(text).not.toContain("Presentes");
  });

  it("atrasado usa o rótulo Atrasado e também não mostra números", () => {
    renderModal(vi.fn(), {
      ...report,
      status: "atrasado",
      presentes: null,
      visitantes: null,
      decisoes: null,
      oferta: null,
      observacoes: null,
    });
    const text = container.textContent ?? "";
    expect(text).toContain("Atrasado");
    expect(text).not.toContain("Presentes");
  });
});
