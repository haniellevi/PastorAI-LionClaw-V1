// @vitest-environment jsdom
/**
 * JevModal — status, configuração pelo console e teste de conexão do Jev.
 *  - carrega o status e mostra chave configurada, modelo e igrejas;
 *  - sem chave: "Testar conexão" fica desabilitado;
 *  - testar mostra o resultado sintético; erro vira banner role="alert";
 *  - o formulário salva a configuração e nunca mostra a chave de volta;
 *  - sem a lista de igrejas do console, salvar mantém as igrejas salvas.
 *
 * Sem JSX (createElement): o tsconfig do Next usa jsx:"preserve".
 */
import { act, createElement as h } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { JevModal, type JevModalProps } from "./JevModal";

const { fetchJevStatus, saveJevConfig, testJev } = vi.hoisted(() => ({
  fetchJevStatus: vi.fn(),
  saveJevConfig: vi.fn(),
  testJev: vi.fn(),
}));

vi.mock("@/lib/admin-api", () => ({
  fetchJevStatus,
  saveJevConfig,
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
  chaveOrigem: "ambiente" as const,
  chaveIlegivel: false,
  chaveAtualizadaEm: null,
  dpaAssinadoEm: null as string | null,
  integradoAoAgente: false,
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

const IGREJAS = [
  { id: "i1", nome: "Igreja Piloto" },
  { id: "i3", nome: "Igreja Fortaleza" },
];

function render(props: Partial<JevModalProps> = {}) {
  act(() => {
    root.render(
      h(JevModal, {
        token: "tok",
        igrejas: IGREJAS,
        onClose: () => {},
        onExpired: () => {},
        ...props,
      }),
    );
  });
}

function input(id: string): HTMLInputElement {
  return document.getElementById(id) as HTMLInputElement;
}

function setValue(el: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
  act(() => {
    setter.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

function checkbox(label: string): HTMLInputElement {
  const found = [...document.querySelectorAll("label")].find((l) =>
    l.textContent!.includes(label),
  );
  return found!.querySelector("input") as HTMLInputElement;
}

function submitConfig() {
  const form = document.querySelector('form[aria-label="Configuração do Jev"]')!;
  act(() => {
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
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
  saveJevConfig.mockReset();
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
    expect(text).toContain("Não integrada");
    expect(text).toContain("sem efeito até a integração");
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

  it("preenche o formulário com a configuração em vigor", async () => {
    fetchJevStatus.mockResolvedValue({ ...STATUS, dpaAssinadoEm: "2026-09-20" });
    render();
    await flush();

    expect(input("jev-chave").value).toBe("");
    expect(input("jev-chave").type).toBe("password");
    expect(input("jev-modelo").value).toBe("jev-latest");
    expect(input("jev-timeout").value).toBe("2");
    expect(input("jev-dpa").value).toBe("2026-09-20");
    expect(document.body.textContent).toContain("Assinado em 20/09/2026");
    expect(checkbox("Igreja Piloto").checked).toBe(true);
    expect(checkbox("Igreja Fortaleza").checked).toBe(false);
  });

  it("sem data do DPA, as igrejas ficam travadas e a lista vai vazia", async () => {
    fetchJevStatus.mockResolvedValue({ ...STATUS, igrejas: [], idsInvalidos: 0 });
    saveJevConfig.mockResolvedValue({ ...STATUS, igrejas: [], idsInvalidos: 0 });
    render();
    await flush();

    const fieldset = checkbox("Igreja Piloto").closest("fieldset")!;
    expect(fieldset.disabled).toBe(true);
    expect(document.body.textContent).toContain("Libera depois de informar a data do DPA");

    submitConfig();
    await flush();
    expect(saveJevConfig).toHaveBeenCalledWith(
      "tok",
      expect.objectContaining({ dpaAssinadoEm: null, igrejaIds: [] }),
    );
  });

  it("salva a configuração, limpa a chave digitada e nunca a mostra", async () => {
    fetchJevStatus.mockResolvedValue({ ...STATUS, configurado: false, chaveOrigem: null });
    saveJevConfig.mockResolvedValue({
      ...STATUS,
      chaveOrigem: "console",
      chaveAtualizadaEm: "2026-09-26T12:00:00+00:00",
      modelo: "jev-1.13",
      timeoutSegundos: 1.5,
      dpaAssinadoEm: "2026-09-20",
      igrejas: [
        { id: "i1", nome: "Igreja Piloto" },
        { id: "i3", nome: "Igreja Fortaleza" },
      ],
      idsInvalidos: 0,
    });
    render();
    await flush();

    setValue(input("jev-chave"), "tsk-segredo-digitado");
    setValue(input("jev-modelo"), "jev-1.13");
    setValue(input("jev-timeout"), "1.5");
    setValue(input("jev-dpa"), "2026-09-20");
    act(() => checkbox("Igreja Fortaleza").click());
    submitConfig();
    await flush();

    expect(saveJevConfig).toHaveBeenCalledWith("tok", {
      apiKey: "tsk-segredo-digitado",
      removerChave: undefined,
      modelo: "jev-1.13",
      timeoutSegundos: 1.5,
      dpaAssinadoEm: "2026-09-20",
      // i2 (igreja que não existe mais) sai da lista ao salvar.
      igrejaIds: ["i1", "i3"],
    });
    expect(input("jev-chave").value).toBe("");
    expect(document.body.textContent).toContain("Configuração salva.");
    expect(document.body.textContent).toContain("Configurada no console");
    expect(document.body.innerHTML).not.toContain("tsk-segredo-digitado");
  });

  it("sem a lista do console carregada, salvar mantém as igrejas salvas", async () => {
    fetchJevStatus.mockResolvedValue({ ...STATUS, dpaAssinadoEm: "2026-09-20" });
    saveJevConfig.mockResolvedValue({ ...STATUS, dpaAssinadoEm: "2026-09-20" });
    render({ igrejas: undefined });
    await flush();

    expect(document.body.textContent).toContain("Lista de igrejas indisponível");
    setValue(input("jev-timeout"), "1.5");
    submitConfig();
    await flush();

    expect(saveJevConfig).toHaveBeenCalledWith(
      "tok",
      // i1 continua; i2 volta do status sem nome (não existe mais) e sai.
      expect.objectContaining({ timeoutSegundos: 1.5, igrejaIds: ["i1"] }),
    );
  });

  it("recusa do backend vira alerta e mantém o formulário", async () => {
    fetchJevStatus.mockResolvedValue(STATUS);
    saveJevConfig.mockRejectedValue(
      new Error("Informe a data do DPA com a TypeSafe antes de listar igrejas."),
    );
    render();
    await flush();

    submitConfig();
    await flush();

    expect(document.querySelector('[role="alert"]')?.textContent).toContain("data do DPA");
    expect(input("jev-modelo").value).toBe("jev-latest");
  });

  it("chave salva ilegível pede para cadastrar de novo", async () => {
    fetchJevStatus.mockResolvedValue({
      ...STATUS,
      configurado: false,
      chaveOrigem: null,
      chaveIlegivel: true,
    });
    render();
    await flush();

    expect(document.body.textContent).toContain("cole a chave de novo");
  });
});
