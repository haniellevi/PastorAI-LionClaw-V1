// @vitest-environment jsdom
/**
 * JevModal — status somente leitura da triagem Jev + teste de conexão.
 *  - carrega o status e mostra chave configurada, modelo e igrejas;
 *  - sem chave: "Testar conexão" fica desabilitado;
 *  - testar mostra o resultado sintético; erro vira banner role="alert".
 *
 * Sem JSX (createElement): o tsconfig do Next usa jsx:"preserve".
 */
import { act, createElement as h } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { JevModal } from "./JevModal";

const { fetchJevStatus, testJev } = vi.hoisted(() => ({
  fetchJevStatus: vi.fn(),
  testJev: vi.fn(),
}));

vi.mock("@/lib/admin-api", () => ({
  fetchJevStatus,
  testJev,
  AdminSessionExpiredError: class AdminSessionExpiredError extends Error {},
}));

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

const STATUS = {
  configurado: true,
  enviosExternosPermitidos: true,
  modelo: "jev-latest",
  timeoutSegundos: 2,
  igrejas: [
    { id: "i1", nome: "Igreja Piloto" },
    { id: "i2", nome: null },
  ],
  idsInvalidos: 1,
};

function flush() {
  return act(async () => {
    await new Promise((r) => setTimeout(r, 0));
  });
}

function render() {
  act(() => {
    root.render(h(JevModal, { token: "tok", onClose: () => {}, onExpired: () => {} }));
  });
}

function findButton(label: string): HTMLButtonElement | undefined {
  return [...document.querySelectorAll("button")].find((b) => b.textContent!.includes(label));
}

beforeEach(() => {
  Object.defineProperty(HTMLElement.prototype, "offsetParent", {
    configurable: true,
    get() {
      return (this as HTMLElement).parentElement;
    },
  });
  fetchJevStatus.mockReset();
  testJev.mockReset();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe("JevModal", () => {
  it("mostra o status da configuração sem expor a chave", async () => {
    fetchJevStatus.mockResolvedValue(STATUS);
    render();
    await flush();

    const text = document.body.textContent!;
    expect(document.querySelector(".ds-dialog-title")?.textContent).toBe("Triagem Jev");
    expect(text).toContain("Configurada");
    expect(text).toContain("jev-latest");
    expect(text).toContain("Igreja Piloto");
    expect(text).toContain("i2 (não encontrada)");
    expect(text).toContain("1 id(s) inválido(s)");
    expect(findButton("Testar conexão")?.disabled).toBe(false);
  });

  it("sem chave, o teste fica desabilitado", async () => {
    fetchJevStatus.mockResolvedValue({ ...STATUS, configurado: false, igrejas: [] });
    render();
    await flush();

    expect(document.body.textContent).toContain("Não configurada");
    expect(document.body.textContent).toContain("Nenhuma (desligado)");
    expect(findButton("Testar conexão")?.disabled).toBe(true);
  });

  it("com ALLOW_REAL_SENDS desligado, o teste fica desabilitado", async () => {
    fetchJevStatus.mockResolvedValue({ ...STATUS, enviosExternosPermitidos: false });
    render();
    await flush();

    expect(document.body.textContent).toContain("Desligados");
    expect(findButton("Testar conexão")?.disabled).toBe(true);
  });

  it("testar conexão mostra o resultado; falha vira alerta", async () => {
    fetchJevStatus.mockResolvedValue(STATUS);
    testJev.mockResolvedValueOnce({
      ok: true,
      modelo: "jev-1.13.0",
      latenciaMs: 850,
      intencao: "pedido_oracao",
      riscoPastoral: 0.06,
      pedeOptout: 0.01,
    });
    render();
    await flush();

    act(() => findButton("Testar conexão")!.click());
    await flush();
    expect(testJev).toHaveBeenCalledWith("tok");
    expect(document.body.textContent).toContain("850 ms");
    expect(document.body.textContent).toContain("pedido_oracao");

    testJev.mockRejectedValueOnce(new Error("Jev indisponível ou resposta inesperada"));
    act(() => findButton("Testar conexão")!.click());
    await flush();
    expect(document.querySelector('[role="alert"]')?.textContent).toContain("Jev indisponível");
  });
});
