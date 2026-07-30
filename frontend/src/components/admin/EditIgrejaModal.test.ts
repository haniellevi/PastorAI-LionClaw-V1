// @vitest-environment jsdom
/**
 * W4B — EditIgrejaModal migrado para o DsDialog. Além dos ganhos de a11y do
 * primitive, garante o comportamento próprio da edição:
 *  - título do diálogo = nome atual da igreja;
 *  - foco inicial no primeiro campo;
 *  - submit por Enter envia SÓ os campos alterados; sem alteração, apenas fecha;
 *  - busy desabilita Cancelar e coloca o primário em loading;
 *  - erro aparece no banner role="alert";
 *  - a zona destrutiva segue no corpo: pede window.confirm antes de onDelete.
 *
 * Sem JSX (createElement): o tsconfig do Next usa jsx:"preserve".
 */
import { act, createElement as h, Fragment, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AdminIgreja, UpdateIgrejaInput } from "@/lib/admin-api";

import { EditIgrejaModal } from "./EditIgrejaModal";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const igreja: AdminIgreja = {
  id: "ig1",
  nome: "Igreja Central",
  status: "ativa",
  plano: "ate_100",
  setupFeeOverride: null,
  membros: 42,
  pessoas: 120,
  createdAt: null,
};

let container: HTMLDivElement;
let root: Root;

function render(props: Partial<Parameters<typeof EditIgrejaModal>[0]> = {}) {
  act(() => {
    root.render(
      h(EditIgrejaModal, {
        igreja,
        busy: false,
        error: null,
        onClose: () => {},
        onSubmit: () => {},
        onDelete: () => {},
        ...props,
      }),
    );
  });
}

function findButton(label: string): HTMLButtonElement | undefined {
  return [...container.querySelectorAll("button")].find((b) => b.textContent!.includes(label));
}

function setValue(el: HTMLInputElement | HTMLSelectElement, value: string) {
  const proto = el instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, "value")!.set!;
  const evt = el instanceof HTMLSelectElement ? "change" : "input";
  act(() => {
    setter.call(el, value);
    el.dispatchEvent(new Event(evt, { bubbles: true }));
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
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.unstubAllGlobals();
});

describe("EditIgrejaModal — W4B (DsDialog)", () => {
  it("título do diálogo é o nome da igreja e o foco inicial vai ao primeiro campo", () => {
    render();
    const title = document.querySelector<HTMLElement>(".ds-dialog-title");
    expect(title?.textContent).toBe("Igreja Central");
    expect(document.activeElement).toBe(document.querySelector("[data-autofocus]"));
  });

  it("submit por Enter envia só os campos alterados", () => {
    const onSubmit = vi.fn<(i: UpdateIgrejaInput) => void>();
    render({ onSubmit });

    setValue(document.getElementById("ei-status") as HTMLSelectElement, "suspensa");
    submitForm();

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit).toHaveBeenCalledWith({ status: "suspensa" });
  });

  it("envia a exceção de setup e permite limpar para voltar ao padrão", () => {
    const onSubmit = vi.fn<(i: UpdateIgrejaInput) => void>();
    render({ igreja: { ...igreja, setupFeeOverride: 40 }, onSubmit });

    const setupInput = container.querySelector<HTMLInputElement>('input[type="number"]')!;
    setValue(setupInput, "25.5");
    submitForm();
    expect(onSubmit).toHaveBeenLastCalledWith({ setupFeeOverride: 25.5 });

    render({ igreja: { ...igreja, setupFeeOverride: 40 }, onSubmit });
    const resetInput = container.querySelector<HTMLInputElement>('input[type="number"]')!;
    setValue(resetInput, "");
    submitForm();
    expect(onSubmit).toHaveBeenLastCalledWith({ setupFeeOverride: null });
  });

  it("sem nenhuma alteração, submit apenas fecha (não chama onSubmit)", () => {
    const onSubmit = vi.fn();
    const onClose = vi.fn();
    render({ onSubmit, onClose });
    submitForm();
    expect(onSubmit).not.toHaveBeenCalled();
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("busy: Cancelar desabilitado e primário em loading", () => {
    render({ busy: true });
    expect(findButton("Cancelar")!.disabled).toBe(true);
    const primary = findButton("Salvando…")!;
    expect(primary.disabled).toBe(true);
    expect(primary.getAttribute("aria-busy")).toBe("true");
  });

  it("erro aparece no banner role=alert", () => {
    render({ error: "Não foi possível atualizar." });
    const banner = container.querySelector('.error-banner[role="alert"]')!;
    expect(banner.textContent).toContain("Não foi possível atualizar.");
  });

  it("fechar por backdrop: mousedown no overlay chama onClose e faz preventDefault", () => {
    // Regressão do smoke DEV W4B: ao fechar por backdrop, o foco terminava no
    // <body> em vez de voltar ao opener. Causa: o mousedown no backdrop (não
    // focável) move o foco para o body DEPOIS do handler, sobrescrevendo o
    // retorno de foco do primitive. A correção é preventDefault no mousedown do
    // overlay — verificável aqui pelo defaultPrevented (jsdom não modela o
    // "clobber" de foco do navegador; o defaultPrevented é o contrato do fix).
    const onClose = vi.fn();
    render({ onClose });
    const overlay = container.querySelector<HTMLElement>(".ds-overlay")!;
    const evt = new MouseEvent("mousedown", { bubbles: true, cancelable: true });
    act(() => {
      overlay.dispatchEvent(evt);
    });
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(evt.defaultPrevented).toBe(true);
  });

  it("fechar por backdrop devolve o foco ao opener", () => {
    // Fluxo fiel: um botão abre o modal; após fechar por backdrop o foco volta
    // ao botão que abriu (retorno de foco do primitive, agora não sobrescrito).
    function Harness() {
      const [open, setOpen] = useState(false);
      return h(
        Fragment,
        null,
        h("button", { id: "opener", onClick: () => setOpen(true) }, "Editar dados"),
        open
          ? h(EditIgrejaModal, {
              igreja, busy: false, error: null,
              onClose: () => setOpen(false), onSubmit: () => {}, onDelete: () => {},
            })
          : null,
      );
    }
    act(() => root.render(h(Harness)));
    const opener = document.getElementById("opener") as HTMLButtonElement;
    act(() => opener.focus());
    act(() => opener.click());
    expect(document.activeElement).toBe(document.querySelector("[data-autofocus]"));

    const overlay = document.querySelector<HTMLElement>(".ds-overlay")!;
    act(() => overlay.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true })));
    expect(document.activeElement).toBe(opener);
  });

  it("Esc fecha (onClose) quando não está em envio", () => {
    const onClose = vi.fn();
    render({ onClose });
    act(() => {
      document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("busy bloqueia fechar por ESC e por backdrop", () => {
    const onClose = vi.fn();
    render({ busy: true, onClose });
    act(() => {
      document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    });
    const overlay = container.querySelector<HTMLElement>(".ds-overlay")!;
    act(() => {
      overlay.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true }));
    });
    expect(onClose).not.toHaveBeenCalled();
  });

  it("rodapé: primário type=submit ligado ao form via form=", () => {
    render();
    const primary = findButton("Salvar alterações")!;
    expect(primary.getAttribute("type")).toBe("submit");
    expect(primary.getAttribute("form")).toBe("edit-igreja-form");
    expect(container.querySelector("form")!.id).toBe("edit-igreja-form");
    expect(primary.closest("form")).toBeNull();
    expect(primary.closest(".ds-dialog-foot")).not.toBeNull();
  });

  it("Excluir: só chama onDelete se o window.confirm for aceito", () => {
    const onDelete = vi.fn();
    const confirmSpy = vi.fn(() => false);
    vi.stubGlobal("confirm", confirmSpy);

    render({ onDelete });
    const excluir = findButton("Excluir igreja")!;
    // O botão de excluir NÃO submete o form (type=button).
    expect(excluir.getAttribute("type")).toBe("button");

    act(() => excluir.click());
    expect(confirmSpy).toHaveBeenCalledTimes(1);
    expect(onDelete).not.toHaveBeenCalled();

    confirmSpy.mockReturnValue(true);
    act(() => excluir.click());
    expect(onDelete).toHaveBeenCalledTimes(1);
  });
});
