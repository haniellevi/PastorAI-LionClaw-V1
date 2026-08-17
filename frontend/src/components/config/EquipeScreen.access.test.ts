// @vitest-environment jsdom
import { act, createElement as h } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Contact } from "@/lib/contacts-api";

const mocks = vi.hoisted(() => ({
  fetchTeam: vi.fn(),
  fetchContacts: vi.fn(),
  inviteMember: vi.fn(),
  updateRoles: vi.fn(),
  resendInvite: vi.fn(),
  revokeAccess: vi.fn(),
  expireSession: vi.fn(),
  auth: {
    token: "tok-1" as string | null,
    user: {
      appUserId: "u-admin",
      roles: ["admin"],
    } as { appUserId: string; roles: string[] } | null,
  },
}));

vi.mock("@/lib/auth-context", () => ({
  useAuth: () => ({
    token: mocks.auth.token,
    user: mocks.auth.user,
    expireSession: mocks.expireSession,
  }),
}));

vi.mock("@/lib/contacts-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/contacts-api")>(
    "@/lib/contacts-api",
  );
  return { ...actual, fetchContacts: mocks.fetchContacts };
});

vi.mock("@/lib/dashboard-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/dashboard-api")>(
    "@/lib/dashboard-api",
  );
  return { ...actual, fetchTeam: mocks.fetchTeam };
});

vi.mock("@/lib/team-api", () => {
  class TeamConflictError extends Error {}
  return {
    TeamConflictError,
    inviteMember: mocks.inviteMember,
    updateRoles: mocks.updateRoles,
    resendInvite: mocks.resendInvite,
    revokeAccess: mocks.revokeAccess,
  };
});

import { EquipeScreen } from "./EquipeScreen";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

const linkedLeader: Contact = {
  id: "p-linked",
  nome: "Ana Vinculada",
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
  celulaId: "cell-existing",
  liderId: null,
  aptoLider: true,
  liderDeCelula: true,
};

async function flushEffects() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

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
  mocks.auth.token = "tok-1";
  mocks.auth.user = { appUserId: "u-admin", roles: ["admin"] };
  mocks.fetchTeam.mockReset().mockResolvedValue({
    items: [],
    page: 1,
    pageSize: 100,
    total: 0,
  });
  mocks.fetchContacts.mockReset().mockResolvedValue({
    items: [linkedLeader],
    page: 1,
    pageSize: 200,
    total: 1,
  });
  mocks.inviteMember.mockReset().mockResolvedValue({
    usuarioId: "u-new",
    status: "convidado",
    emailEnviado: true,
  });
  mocks.updateRoles.mockReset();
  mocks.resendInvite.mockReset();
  mocks.revokeAccess.mockReset();
  mocks.expireSession.mockReset();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe("EquipeScreen: acesso separado da célula", () => {
  it("permite selecionar Pessoa já vinculada/líder e omite celulaId do convite", async () => {
    act(() => root.render(h(EquipeScreen)));
    await flushEffects();

    const open = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent?.trim() === "Dar acesso ao painel",
    ) as HTMLButtonElement;
    act(() => open.click());
    await flushEffects();

    const personButton = Array.from(container.querySelectorAll("button")).find((button) =>
      button.textContent?.includes("Ana Vinculada"),
    ) as HTMLButtonElement;
    expect(personButton.disabled).toBe(false);
    expect(personButton.textContent).toContain("Lidera célula");
    act(() => personButton.click());

    const submit = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent?.trim() === "Enviar convite",
    ) as HTMLButtonElement;
    expect(submit.disabled).toBe(false);
    await act(async () => {
      submit.click();
      await Promise.resolve();
    });

    expect(mocks.inviteMember).toHaveBeenCalledWith("tok-1", {
      pessoaId: "p-linked",
      email: "ana@example.com",
    });
    expect(mocks.inviteMember.mock.calls[0]?.[1]).not.toHaveProperty("celulaId");
  });

  it("limpa a Pessoa selecionada quando a busca muda e não envia ao alvo oculto", async () => {
    act(() => root.render(h(EquipeScreen)));
    await flushEffects();

    const open = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent?.trim() === "Dar acesso ao painel",
    ) as HTMLButtonElement;
    act(() => open.click());
    await flushEffects();

    const personButton = Array.from(container.querySelectorAll("button")).find((button) =>
      button.textContent?.includes("Ana Vinculada"),
    ) as HTMLButtonElement;
    act(() => personButton.click());

    const submit = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent?.trim() === "Enviar convite",
    ) as HTMLButtonElement;
    expect(submit.disabled).toBe(false);

    changeInput(
      container.querySelector("#invPessoaQuery") as HTMLInputElement,
      "Outra pessoa",
    );

    expect(submit.disabled).toBe(true);
    const form = container.querySelector("form") as HTMLFormElement;
    act(() =>
      form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })),
    );
    expect(mocks.inviteMember).not.toHaveBeenCalled();
  });

  it("não oferece gestão de acesso ao pastor sem papel admin", async () => {
    mocks.auth.user = { appUserId: "u-pastor", roles: ["pastor"] };
    act(() => root.render(h(EquipeScreen)));
    await flushEffects();

    expect(
      Array.from(container.querySelectorAll("button")).some(
        (button) => button.textContent?.trim() === "Dar acesso ao painel",
      ),
    ).toBe(false);
  });

  it("exibe lider_celula como derivado e envia somente papéis manuais", async () => {
    mocks.fetchTeam.mockResolvedValue({
      items: [
        {
          usuarioId: "u-leader",
          pessoaId: "p-leader",
          nome: "Líder Derivada",
          email: "lider@example.com",
          status: "ativo",
          papeis: ["lider_celula"],
        },
      ],
      page: 1,
      pageSize: 100,
      total: 1,
    });
    act(() => root.render(h(EquipeScreen)));
    await flushEffects();

    const edit = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent?.trim() === "Editar papéis",
    ) as HTMLButtonElement;
    act(() => edit.click());

    const derived = container.querySelector(
      '.role-pick input[value="lider_celula"]',
    ) as HTMLInputElement;
    expect(derived.checked).toBe(true);
    expect(derived.disabled).toBe(true);

    const save = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent?.trim() === "Salvar papéis",
    ) as HTMLButtonElement;
    await act(async () => {
      save.click();
      await Promise.resolve();
    });

    expect(mocks.updateRoles).toHaveBeenCalledWith("tok-1", "u-leader", []);
  });

  it("não permite deixar sem papel uma pessoa que não tem liderança derivada", async () => {
    mocks.fetchTeam.mockResolvedValue({
      items: [
        {
          usuarioId: "u-member",
          pessoaId: "p-member",
          nome: "Membro Simples",
          email: "membro@example.com",
          status: "ativo",
          papeis: ["membro"],
        },
      ],
      page: 1,
      pageSize: 100,
      total: 1,
    });
    act(() => root.render(h(EquipeScreen)));
    await flushEffects();

    const edit = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent?.trim() === "Editar papéis",
    ) as HTMLButtonElement;
    act(() => edit.click());
    const memberRole = container.querySelector(
      '.role-pick input[value="membro"]',
    ) as HTMLInputElement;
    act(() => memberRole.click());

    const save = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent?.trim() === "Salvar papéis",
    ) as HTMLButtonElement;
    act(() => save.click());

    expect(mocks.updateRoles).not.toHaveBeenCalled();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain(
      "Selecione ao menos um papel",
    );
  });
});
