// @vitest-environment jsdom
import { act, createElement as h } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Contact } from "@/lib/contacts-api";

const mocks = vi.hoisted(() => ({
  addCellMember: vi.fn(),
  inviteMember: vi.fn(),
  expireSession: vi.fn(),
}));

vi.mock("@/lib/auth-context", () => ({
  useAuth: () => ({ token: "tok-1", expireSession: mocks.expireSession }),
}));

vi.mock("@/lib/cells-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/cells-api")>("@/lib/cells-api");
  return { ...actual, addCellMember: mocks.addCellMember };
});

vi.mock("@/lib/team-api", () => ({ inviteMember: mocks.inviteMember }));

import { AddCellMemberModal } from "./InviteMemberModal";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

const person: Contact = {
  id: "p-1",
  nome: "Ana Pessoa",
  telefone: "55999999999",
  email: "ana@example.com",
  genero: null,
  tipo: "membro",
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

function changeInput(input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype,
    "value",
  )?.set;
  act(() => {
    setter?.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

beforeEach(() => {
  mocks.addCellMember.mockReset().mockResolvedValue({
    id: "cm-1",
    pessoaId: person.id,
    papel: "membro",
    ativo: true,
  });
  mocks.inviteMember.mockReset();
  mocks.expireSession.mockReset();
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

describe("AddCellMemberModal", () => {
  it("vincula Pessoa cadastrada sem convite e mantém o sucesso visível", async () => {
    const onAdded = vi.fn();
    act(() => {
      root.render(
        h(AddCellMemberModal, {
          celulaId: "cell-1",
          celulaNome: "Célula Vida",
          contacts: [person],
          onClose: vi.fn(),
          onAdded,
        }),
      );
    });

    expect(container.textContent).toContain("Adicionar à célula · Célula Vida");
    expect(container.textContent).toContain("não concede acesso ao painel");
    expect(container.textContent).not.toContain("e-mail");

    const personButton = Array.from(container.querySelectorAll("button")).find((button) =>
      button.textContent?.includes("Ana Pessoa"),
    ) as HTMLButtonElement;
    act(() => personButton.click());

    const submit = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === "Adicionar à célula",
    ) as HTMLButtonElement;
    await act(async () => {
      submit.click();
      await Promise.resolve();
    });

    expect(mocks.addCellMember).toHaveBeenCalledWith("tok-1", "cell-1", "p-1");
    expect(mocks.inviteMember).not.toHaveBeenCalled();
    expect(onAdded).toHaveBeenCalledTimes(1);
    expect(container.textContent).toContain("Ana Pessoa foi adicionada à célula");
    expect(container.querySelector('[role="status"]')).not.toBeNull();
    expect(container.textContent).toContain("Concluir");
  });

  it("limpa a Pessoa selecionada quando a busca muda e não vincula alvo oculto", () => {
    act(() => {
      root.render(
        h(AddCellMemberModal, {
          celulaId: "cell-1",
          celulaNome: "Célula Vida",
          contacts: [person],
          onClose: vi.fn(),
          onAdded: vi.fn(),
        }),
      );
    });

    const personButton = Array.from(container.querySelectorAll("button")).find((button) =>
      button.textContent?.includes("Ana Pessoa"),
    ) as HTMLButtonElement;
    act(() => personButton.click());

    const submit = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === "Adicionar à célula",
    ) as HTMLButtonElement;
    expect(submit.disabled).toBe(false);

    changeInput(
      container.querySelector("#addCellMemberQuery") as HTMLInputElement,
      "Outra pessoa",
    );

    expect(submit.disabled).toBe(true);
    const form = container.querySelector("form") as HTMLFormElement;
    act(() =>
      form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })),
    );
    expect(mocks.addCellMember).not.toHaveBeenCalled();
    expect(mocks.inviteMember).not.toHaveBeenCalled();
  });

  it("não oferece pastor como candidato a membro da célula", () => {
    act(() => {
      root.render(
        h(AddCellMemberModal, {
          celulaId: "cell-1",
          celulaNome: "Célula Vida",
          contacts: [
            {
              ...person,
              id: "p-pastor",
              nome: "Pastor Oficial",
              tipo: "pastor",
            },
          ],
          onClose: vi.fn(),
          onAdded: vi.fn(),
        }),
      );
    });

    expect(container.textContent).not.toContain("Pastor Oficial");
    expect(container.textContent).toContain("Nenhuma Pessoa elegível");
  });
});
