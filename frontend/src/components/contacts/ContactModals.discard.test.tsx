// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Contact } from "@/lib/contacts-api";

import { EditContactModal } from "./EditContactModal";
import { NewContactModal } from "./NewContactModal";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const contact: Contact = {
  id: "synthetic-contact",
  nome: "Pessoa sintética",
  telefone: "5500000000000",
  email: null,
  genero: null,
  tipo: "contato",
  etapa: null,
  subetapa: null,
  acompanhamento: null,
  semInteresse: false,
  semInteresseMotivo: null,
  presencasCelula: 0,
  aceitouJesus: false,
  celulaId: null,
  liderId: null,
  aptoLider: false,
  liderDeCelula: false,
};

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe.each(["novo", "edição"] as const)("Modal de contato (%s), descarte", (mode) => {
  function renderModal(busy: boolean, onSubmit: () => void, onClose: () => void) {
    act(() => root.render(mode === "novo"
      ? <NewContactModal busy={busy} error={null} onSubmit={onSubmit} onClose={onClose} />
      : <EditContactModal contact={contact} busy={busy} error={null} onSubmit={onSubmit} onClose={onClose} />));
  }

  function button(text: string): HTMLButtonElement {
    const found = Array.from(container.querySelectorAll("button")).find((el) => el.textContent?.trim() === text);
    if (!found) throw new Error(`Botão ausente: ${text}`);
    return found;
  }

  function fillValidContact() {
    const values = ["Pessoa sintética editada", contact.telefone];
    act(() => {
      Array.from(container.querySelectorAll<HTMLInputElement>("input")).slice(0, 2).forEach((input, index) => {
        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, values[index]);
        input.dispatchEvent(new Event("input", { bubbles: true }));
      });
    });
  }

  function submitForm() {
    act(() => container.querySelector("form")!.requestSubmit());
  }

  it("bloqueia submit com descarte aberto e mantém o rascunho", () => {
    const onSubmit = vi.fn();
    const onClose = vi.fn();
    renderModal(false, onSubmit, onClose);
    fillValidContact();
    act(() => button("Cancelar").click());

    submitForm();

    expect(onSubmit).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
    expect(container.querySelector<HTMLButtonElement>('button[type="submit"]')!.disabled).toBe(true);
    expect(container.querySelector<HTMLInputElement>("input")!.value).toBe("Pessoa sintética editada");
  });

  it("bloqueia descarte e submit se uma escrita está pendente", () => {
    const onSubmit = vi.fn();
    const onClose = vi.fn();
    renderModal(false, onSubmit, onClose);
    fillValidContact();
    act(() => button("Cancelar").click());
    renderModal(true, onSubmit, onClose);

    expect(button("Continuar editando").disabled).toBe(true);
    expect(button("Descartar alterações").disabled).toBe(true);
    act(() => button("Descartar alterações").click());
    submitForm();
    expect(onClose).not.toHaveBeenCalled();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("bloqueia submit durante busy mesmo sem confirmação de descarte", () => {
    const onSubmit = vi.fn();
    const onClose = vi.fn();
    renderModal(false, onSubmit, onClose);
    fillValidContact();
    renderModal(true, onSubmit, onClose);

    submitForm();

    expect(onSubmit).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("permite salvar depois de continuar editando, preservando o payload", () => {
    const onSubmit = vi.fn();
    const onClose = vi.fn();
    renderModal(false, onSubmit, onClose);
    fillValidContact();
    act(() => button("Cancelar").click());
    act(() => button("Continuar editando").click());

    submitForm();

    expect(onSubmit).toHaveBeenCalledExactlyOnceWith(mode === "novo"
      ? { nome: "Pessoa sintética editada", telefone: contact.telefone, email: null, genero: null, tipo: "contato" }
      : { nome: "Pessoa sintética editada" });
    expect(onClose).not.toHaveBeenCalled();
  });

  it("descarta sem enviar quando não há escrita pendente", () => {
    const onSubmit = vi.fn();
    const onClose = vi.fn();
    renderModal(false, onSubmit, onClose);
    fillValidContact();
    act(() => button("Cancelar").click());
    act(() => button("Descartar alterações").click());

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onSubmit).not.toHaveBeenCalled();
  });
});
