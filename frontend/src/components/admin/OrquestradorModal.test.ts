// @vitest-environment jsdom
/**
 * W4B — OrquestradorModal migrado para o DsDialog. Cobre o comportamento
 * próprio do modal, que carrega os dados por conta própria:
 *  - loading inicial (spinner) enquanto o fetch não resolve — sem campos nem
 *    rodapé de ações;
 *  - carregado: campos e rodapé aparecem, título = "Orquestrador";
 *  - submit por Enter salva com os valores aparados e mostra o aviso de sucesso;
 *  - validação: comportamento vazio vira erro no banner role="alert";
 *  - busy (durante o save) desabilita Fechar e coloca o primário em loading;
 *  - Esc fecha (onClose).
 *
 * Sem JSX (createElement): o tsconfig do Next usa jsx:"preserve".
 */
import { act, createElement as h } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OrquestradorModal } from "./OrquestradorModal";

const { fetchOrquestrador, saveOrquestrador } = vi.hoisted(() => ({
  fetchOrquestrador: vi.fn(),
  saveOrquestrador: vi.fn(),
}));

vi.mock("@/lib/admin-api", () => ({
  fetchOrquestrador,
  saveOrquestrador,
  AdminSessionExpiredError: class AdminSessionExpiredError extends Error {},
}));

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

function flush() {
  return act(async () => {
    await new Promise((r) => setTimeout(r, 0));
  });
}

function render(props: Partial<Parameters<typeof OrquestradorModal>[0]> = {}) {
  act(() => {
    root.render(
      h(OrquestradorModal, {
        token: "tok",
        onClose: () => {},
        onExpired: () => {},
        ...props,
      }),
    );
  });
}

function findButton(label: string): HTMLButtonElement | undefined {
  return [...container.querySelectorAll("button")].find((b) => b.textContent!.includes(label));
}

function setValue(el: HTMLInputElement | HTMLTextAreaElement, value: string) {
  const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, "value")!.set!;
  act(() => {
    setter.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

function submitForm() {
  const form = container.querySelector("form")!;
  act(() => {
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
}

beforeEach(() => {
  Object.defineProperty(HTMLElement.prototype, "offsetParent", {
    configurable: true,
    get() {
      return (this as HTMLElement).parentElement;
    },
  });
  fetchOrquestrador.mockReset();
  saveOrquestrador.mockReset();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe("OrquestradorModal — W4B (DsDialog)", () => {
  it("mostra o loading inicial e depois revela os campos e o rodapé", async () => {
    const d = deferred<{ nome: string; tom: string; comportamento: string }>();
    fetchOrquestrador.mockReturnValue(d.promise);

    render();
    // Enquanto não carregou: spinner, sem campos, sem botão de salvar.
    expect(container.textContent).toContain("Carregando…");
    expect(container.querySelector("#orq-comp")).toBeNull();
    expect(findButton("Salvar modelo")).toBeUndefined();
    expect(document.querySelector(".ds-dialog-title")?.textContent).toBe("Orquestrador");

    d.resolve({ nome: "Assistente", tom: "acolhedor", comportamento: "seja gentil" });
    await flush();

    expect(container.querySelector("#orq-comp")).not.toBeNull();
    expect(findButton("Salvar modelo")).toBeDefined();
    expect(findButton("Fechar")).toBeDefined();
  });

  it("submit por Enter salva os valores aparados e mostra o aviso de sucesso", async () => {
    fetchOrquestrador.mockResolvedValue({ nome: "", tom: "", comportamento: "" });
    saveOrquestrador.mockResolvedValue(undefined);

    render();
    await flush();

    setValue(document.getElementById("orq-nome") as HTMLInputElement, "  Ana  ");
    setValue(document.getElementById("orq-comp") as HTMLTextAreaElement, "  seja acolhedora  ");
    submitForm();
    await flush();

    expect(saveOrquestrador).toHaveBeenCalledTimes(1);
    expect(saveOrquestrador).toHaveBeenCalledWith("tok", {
      comportamento: "seja acolhedora",
      nome: "Ana",
      tom: null,
    });
    expect(container.textContent).toContain("Modelo do orquestrador salvo.");
  });

  it("comportamento vazio vira erro no banner role=alert", async () => {
    fetchOrquestrador.mockResolvedValue({ nome: "", tom: "", comportamento: "" });
    render();
    await flush();

    submitForm();
    expect(saveOrquestrador).not.toHaveBeenCalled();
    const banner = container.querySelector('.error-banner[role="alert"]')!;
    expect(banner.textContent).toContain("Descreva o comportamento do orquestrador.");
  });

  it("busy durante o save: Fechar desabilitado e primário em loading", async () => {
    fetchOrquestrador.mockResolvedValue({ nome: "", tom: "", comportamento: "algo" });
    const pending = deferred<void>();
    saveOrquestrador.mockReturnValue(pending.promise);

    render();
    await flush();

    submitForm();
    await flush();

    expect(findButton("Fechar")!.disabled).toBe(true);
    const primary = findButton("Salvando…")!;
    expect(primary).toBeDefined();
    expect(primary.disabled).toBe(true);

    pending.resolve();
    await flush();
  });

  it("Esc fecha (onClose)", async () => {
    fetchOrquestrador.mockResolvedValue({ nome: "", tom: "", comportamento: "algo" });
    const onClose = vi.fn();
    render({ onClose });
    await flush();

    act(() => {
      document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    });
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
