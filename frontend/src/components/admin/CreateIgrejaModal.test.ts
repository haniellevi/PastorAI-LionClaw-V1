// @vitest-environment jsdom
/**
 * W4B — CreateIgrejaModal migrado para o DsDialog. Cobre o que o primitive
 * passa a garantir e o que precisa continuar igual:
 *  - abertura com foco inicial no primeiro campo ([data-autofocus]) e retorno
 *    do foco ao gatilho quando o diálogo fecha;
 *  - Esc e mousedown no backdrop fecham (onClose);
 *  - Tab/Shift+Tab presos dentro do diálogo;
 *  - submit por Enter (evento submit no form) valida e envia o payload;
 *  - busy desabilita Cancelar e coloca o primário em loading;
 *  - erro do backend aparece no banner role="alert";
 *  - o botão primário mora no rodapé, mas continua ligado ao form via form=.
 *
 * Sem JSX (createElement): o tsconfig do Next usa jsx:"preserve".
 */
import { act, createElement as h } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { CreateIgrejaInput } from "@/lib/admin-api";

import { CreateIgrejaModal } from "./CreateIgrejaModal";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

function render(props: Partial<Parameters<typeof CreateIgrejaModal>[0]> = {}) {
  act(() => {
    root.render(
      h(CreateIgrejaModal, {
        busy: false,
        error: null,
        onClose: () => {},
        onSubmit: () => {},
        ...props,
      }),
    );
  });
}

function findButton(label: string): HTMLButtonElement | undefined {
  return [...container.querySelectorAll("button")].find((b) => b.textContent!.includes(label));
}

function focusables(): HTMLElement[] {
  const panel = document.querySelector<HTMLElement>('[role="dialog"]')!;
  return [...panel.querySelectorAll<HTMLElement>("button, input, select, textarea, [tabindex]")].filter(
    (el) => !(el as HTMLButtonElement).disabled,
  );
}

function setValue(el: HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement, value: string) {
  const proto =
    el instanceof HTMLSelectElement
      ? HTMLSelectElement.prototype
      : el instanceof HTMLTextAreaElement
        ? HTMLTextAreaElement.prototype
        : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, "value")!.set!;
  const evt = el instanceof HTMLSelectElement ? "change" : "input";
  act(() => {
    setter.call(el, value);
    el.dispatchEvent(new Event(evt, { bubbles: true }));
  });
}

function fieldByLabel(label: string): HTMLInputElement {
  const lab = [...container.querySelectorAll("label")].find((l) => l.textContent!.includes(label))!;
  return document.getElementById(lab.htmlFor) as HTMLInputElement;
}

function submitForm() {
  const form = container.querySelector("form")!;
  act(() => {
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
}

function pressKey(key: string, shiftKey = false) {
  act(() => {
    document.dispatchEvent(new KeyboardEvent("keydown", { key, shiftKey, bubbles: true }));
  });
}

beforeEach(() => {
  // jsdom não implementa layout: offsetParent (filtro do getFocusable) vira o
  // pai direto — todos os controles contam como visíveis.
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
});

describe("CreateIgrejaModal — W4B (DsDialog)", () => {
  it("abre com foco inicial no primeiro campo e retorna o foco ao gatilho ao fechar", () => {
    const opener = document.createElement("button");
    document.body.appendChild(opener);
    opener.focus();

    render();
    const autofocused = document.querySelector<HTMLElement>("[data-autofocus]");
    expect(autofocused).not.toBeNull();
    expect(document.activeElement).toBe(autofocused);

    // Fechar = pai deixa de renderizar o modal (open é fixo em true).
    act(() => root.render(null));
    expect(document.activeElement).toBe(opener);
    opener.remove();
  });

  it("Esc fecha (onClose)", () => {
    const onClose = vi.fn();
    render({ onClose });
    pressKey("Escape");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("mousedown no backdrop fecha (onClose)", () => {
    const onClose = vi.fn();
    render({ onClose });
    const overlay = container.querySelector<HTMLElement>(".ds-overlay")!;
    act(() => {
      overlay.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
    });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("Tab e Shift+Tab ficam presos dentro do diálogo", () => {
    render();
    const items = focusables();
    const first = items[0]!;
    const last = items[items.length - 1]!;

    act(() => last.focus());
    pressKey("Tab");
    expect(document.activeElement).toBe(first);

    act(() => first.focus());
    pressKey("Tab", true);
    expect(document.activeElement).toBe(last);
  });

  it("submit por Enter valida e envia só com os campos válidos", () => {
    const onSubmit = vi.fn<(i: CreateIgrejaInput) => void>();
    render({ onSubmit });

    // Vazio: submit não envia e marca erros de validação.
    submitForm();
    expect(onSubmit).not.toHaveBeenCalled();
    expect(container.textContent).toContain("Informe o nome da igreja.");

    setValue(fieldByLabel("Nome da igreja"), "  Igreja Nova  ");
    setValue(fieldByLabel("Administrador — nome"), " Pastor João ");
    setValue(fieldByLabel("Administrador — e-mail"), " joao@igreja.com ");
    submitForm();

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit).toHaveBeenCalledWith({
      nome: "Igreja Nova",
      plano: null,
      setupFeeOverride: null,
      admin: { nome: "Pastor João", email: "joao@igreja.com" },
    });
  });

  it("envia a taxa de setup personalizada quando o master a informa", () => {
    const onSubmit = vi.fn<(i: CreateIgrejaInput) => void>();
    render({ onSubmit });

    setValue(fieldByLabel("Nome da igreja"), "Igreja Nova");
    setValue(fieldByLabel("Taxa de setup personalizada"), "39.9");
    setValue(fieldByLabel("Administrador — nome"), "Pastor João");
    setValue(fieldByLabel("Administrador — e-mail"), "joao@igreja.com");
    submitForm();

    expect(onSubmit).toHaveBeenCalledWith({
      nome: "Igreja Nova",
      plano: null,
      setupFeeOverride: 39.9,
      admin: { nome: "Pastor João", email: "joao@igreja.com" },
    });
  });

  it("bloqueia já no primeiro submit uma taxa entre R$ 0,01 e R$ 4,99", () => {
    const onSubmit = vi.fn<(i: CreateIgrejaInput) => void>();
    render({ onSubmit });

    setValue(fieldByLabel("Nome da igreja"), "Igreja Nova");
    setValue(fieldByLabel("Taxa de setup personalizada"), "4.99");
    setValue(fieldByLabel("Administrador — nome"), "Pastor João");
    setValue(fieldByLabel("Administrador — e-mail"), "joao@igreja.com");
    submitForm();

    expect(onSubmit).not.toHaveBeenCalled();
    expect(container.textContent).toContain(
      "Taxa de setup deve ser R$ 0,00 (isenta) ou de pelo menos R$ 5,00.",
    );

    // R$ 0,00 (isenta) é aceito.
    setValue(fieldByLabel("Taxa de setup personalizada"), "0");
    submitForm();
    expect(onSubmit).toHaveBeenCalledWith({
      nome: "Igreja Nova",
      plano: null,
      setupFeeOverride: 0,
      admin: { nome: "Pastor João", email: "joao@igreja.com" },
    });
  });

  it("o botão primário fica no rodapé, ligado ao form via form=", () => {
    render();
    const primary = findButton("Provisionar igreja")!;
    expect(primary.getAttribute("type")).toBe("submit");
    expect(primary.getAttribute("form")).toBe("create-igreja-form");
    expect(container.querySelector("form")!.id).toBe("create-igreja-form");
    // O primário está no rodapé do DsDialog, não dentro do <form>.
    expect(primary.closest("form")).toBeNull();
    expect(primary.closest(".ds-dialog-foot")).not.toBeNull();
  });

  it("busy: Cancelar desabilitado e primário em loading", () => {
    render({ busy: true });
    const cancelar = findButton("Cancelar")!;
    expect(cancelar.disabled).toBe(true);
    const primary = findButton("Provisionando…")!;
    expect(primary).toBeDefined();
    expect(primary.disabled).toBe(true);
    expect(primary.getAttribute("aria-busy")).toBe("true");
  });

  it("busy bloqueia fechar por ESC e por backdrop", () => {
    const onClose = vi.fn();
    render({ busy: true, onClose });
    pressKey("Escape");
    const overlay = container.querySelector<HTMLElement>(".ds-overlay")!;
    act(() => {
      overlay.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true }));
    });
    expect(onClose).not.toHaveBeenCalled();
  });

  it("erro do backend aparece no banner role=alert", () => {
    render({ error: "Plano inválido." });
    const banner = container.querySelector('.error-banner[role="alert"]')!;
    expect(banner.textContent).toContain("Plano inválido.");
  });
});
