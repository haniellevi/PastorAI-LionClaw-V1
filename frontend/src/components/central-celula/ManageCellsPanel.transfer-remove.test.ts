// @vitest-environment jsdom
import { act, createElement as h } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { CellMembro, CellSummary } from "@/lib/cells-api";
import type { Contact } from "@/lib/contacts-api";

const mocks = vi.hoisted(() => ({
  fetchCellsFull: vi.fn(),
  fetchCellMembros: vi.fn(),
  upsertCell: vi.fn(),
  fetchContacts: vi.fn(),
  fetchTeam: vi.fn(),
  transferCellMember: vi.fn(),
  removeCellMember: vi.fn(),
  expireSession: vi.fn(),
}));

vi.mock("@/lib/auth-context", () => ({
  useAuth: () => ({ token: "tok-1", expireSession: mocks.expireSession }),
}));

vi.mock("@/lib/cells-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/cells-api")>(
    "@/lib/cells-api",
  );
  return {
    ...actual,
    fetchCellsFull: mocks.fetchCellsFull,
    fetchCellMembros: mocks.fetchCellMembros,
    upsertCell: mocks.upsertCell,
    transferCellMember: mocks.transferCellMember,
    removeCellMember: mocks.removeCellMember,
  };
});

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

vi.mock("./CellHealthList", () => ({ CellHealthList: () => null }));
vi.mock("./PendingReportsList", () => ({ PendingReportsList: () => null }));
vi.mock("./MultiplicationsList", () => ({ MultiplicationsList: () => null }));

import { ManageCellsPanel } from "./ManageCellsPanel";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

function cell(overrides: Partial<CellSummary> = {}): CellSummary {
  return {
    id: "cell-1",
    nome: "Célula Vida",
    liderId: "leader-1",
    diaReuniao: "Quarta-feira",
    horario: "20:00",
    coberturaEspiritual: "Pr. João",
    ativo: true,
    ...overrides,
  };
}

function contact(overrides: Partial<Contact> = {}): Contact {
  return {
    id: "pessoa-1",
    nome: "João da Silva",
    telefone: "+5511999999999",
    email: null,
    genero: null,
    tipo: "membro",
    etapa: null,
    subetapa: null,
    acompanhamento: null,
    semInteresse: false,
    semInteresseMotivo: null,
    presencasCelula: 0,
    aceitouJesus: false,
    celulaId: "cell-1",
    liderId: null,
    aptoLider: false,
    liderDeCelula: false,
    arquivada: false,
    ...overrides,
  };
}

function membro(overrides: Partial<CellMembro> = {}): CellMembro {
  return {
    id: "membro-1",
    pessoaId: "pessoa-1",
    papel: "membro",
    ativo: true,
    ...overrides,
  };
}

async function flushEffects() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
}

beforeEach(() => {
  mocks.fetchCellMembros.mockReset().mockResolvedValue([]);
  mocks.upsertCell.mockReset();
  mocks.transferCellMember.mockReset();
  mocks.removeCellMember.mockReset();
  mocks.fetchContacts.mockReset().mockResolvedValue({
    items: [],
    page: 1,
    pageSize: 200,
    total: 0,
  });
  mocks.fetchTeam.mockReset().mockResolvedValue({
    items: [],
    page: 1,
    pageSize: 100,
    total: 0,
  });
  mocks.expireSession.mockReset();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

async function selectCell() {
  const row = Array.from(container.querySelectorAll("button")).find((button) =>
    button.textContent?.includes("Célula Vida"),
  ) as HTMLButtonElement;
  act(() => row.click());
  await flushEffects();
}

describe("ManageCellsPanel: transferir/remover membro (pós-V1)", () => {
  it("exibe botões Transferir e Remover para cada membro ativo vinculado", async () => {
    mocks.fetchCellsFull.mockReset().mockResolvedValue({
      items: [cell()],
      page: 1,
      pageSize: 200,
      total: 1,
    });
    mocks.fetchCellMembros.mockReset().mockResolvedValue([membro()]);
    mocks.fetchContacts.mockReset().mockResolvedValue({
      items: [contact()],
      page: 1,
      pageSize: 200,
      total: 1,
    });
    act(() => {
      root.render(
        h(ManageCellsPanel, {
          token: "tok-1",
          onToast: vi.fn(),
          onChanged: vi.fn(),
        }),
      );
    });
    await flushEffects();
    await selectCell();

    const transferBtn = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent?.includes("Transferir"),
    ) as HTMLButtonElement;
    const removeBtn = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent?.includes("Remover"),
    ) as HTMLButtonElement;

    expect(transferBtn).toBeTruthy();
    expect(removeBtn).toBeTruthy();
  });

  it("abre modal de transferência ao clicar em Transferir", async () => {
    mocks.fetchCellsFull.mockReset().mockResolvedValue({
      items: [cell(), cell({ id: "cell-2", nome: "Célula Esperança" })],
      page: 1,
      pageSize: 200,
      total: 2,
    });
    mocks.fetchCellMembros.mockReset().mockResolvedValue([membro()]);
    mocks.fetchContacts.mockReset().mockResolvedValue({
      items: [contact()],
      page: 1,
      pageSize: 200,
      total: 1,
    });
    act(() => {
      root.render(
        h(ManageCellsPanel, {
          token: "tok-1",
          onToast: vi.fn(),
          onChanged: vi.fn(),
        }),
      );
    });
    await flushEffects();
    await selectCell();

    const transferBtn = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent?.includes("Transferir"),
    ) as HTMLButtonElement;
    act(() => transferBtn.click());
    await flushEffects();

    // Modal aberto com título "Transferir membro"
    const dialogText = container.textContent ?? "";
    expect(dialogText).toContain("Transferir membro");
    // destino aparece no modal (não na lista de células — o texto exato sem "Líder:")
    const destinoInModal = Array.from(container.querySelectorAll("button")).find(
      (button) =>
        button.textContent?.trim() === "Célula Esperança" &&
        !button.textContent?.includes("Ativa"),
    );
    expect(destinoInModal).toBeTruthy();
  });

  it("abre modal de remoção ao clicar em Remover", async () => {
    mocks.fetchCellsFull.mockReset().mockResolvedValue({
      items: [cell()],
      page: 1,
      pageSize: 200,
      total: 1,
    });
    mocks.fetchCellMembros.mockReset().mockResolvedValue([membro()]);
    mocks.fetchContacts.mockReset().mockResolvedValue({
      items: [contact()],
      page: 1,
      pageSize: 200,
      total: 1,
    });
    act(() => {
      root.render(
        h(ManageCellsPanel, {
          token: "tok-1",
          onToast: vi.fn(),
          onChanged: vi.fn(),
        }),
      );
    });
    await flushEffects();
    await selectCell();

    const removeBtn = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent?.includes("Remover"),
    ) as HTMLButtonElement;
    act(() => removeBtn.click());
    await flushEffects();

    const dialogText = container.textContent ?? "";
    expect(dialogText).toContain("Remover membro");
    expect(dialogText).toContain("não é deletada");
  });

  it("chama transferCellMember ao confirmar a transferência", async () => {
    mocks.fetchCellsFull.mockReset().mockResolvedValue({
      items: [cell(), cell({ id: "cell-2", nome: "Célula Esperança" })],
      page: 1,
      pageSize: 200,
      total: 2,
    });
    mocks.fetchCellMembros.mockReset().mockResolvedValue([membro()]);
    mocks.fetchContacts.mockReset().mockResolvedValue({
      items: [contact()],
      page: 1,
      pageSize: 200,
      total: 1,
    });
    mocks.transferCellMember.mockResolvedValue({
      id: "membro-2",
      pessoaId: "pessoa-1",
      papel: "membro",
      ativo: true,
    });
    act(() => {
      root.render(
        h(ManageCellsPanel, {
          token: "tok-1",
          onToast: vi.fn(),
          onChanged: vi.fn(),
        }),
      );
    });
    await flushEffects();
    await selectCell();

    const transferBtn = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent?.includes("Transferir"),
    ) as HTMLButtonElement;
    act(() => transferBtn.click());
    await flushEffects();

    // Seleciona o destino (botão dentro do modal — texto exato, sem "Líder:"/"Ativa")
    const destinoBtn = Array.from(container.querySelectorAll("button")).find(
      (button) =>
        button.textContent?.trim() === "Célula Esperança" &&
        !button.textContent?.includes("Ativa"),
    ) as HTMLButtonElement;
    act(() => destinoBtn.click());
    await flushEffects();

    // Submete o formulário via dispatchEvent (jsdom não dispara submit com click)
    const form = container.querySelector("form") as HTMLFormElement;
    await act(async () => {
      form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
      await Promise.resolve();
      await Promise.resolve();
    });
    await flushEffects();

    expect(mocks.transferCellMember).toHaveBeenCalledWith(
      "tok-1",
      "cell-1",
      "pessoa-1",
      "cell-2",
      undefined,
    );
  });

  it("chama removeCellMember ao confirmar a remoção", async () => {
    mocks.fetchCellsFull.mockReset().mockResolvedValue({
      items: [cell()],
      page: 1,
      pageSize: 200,
      total: 1,
    });
    mocks.fetchCellMembros.mockReset().mockResolvedValue([membro()]);
    mocks.fetchContacts.mockReset().mockResolvedValue({
      items: [contact()],
      page: 1,
      pageSize: 200,
      total: 1,
    });
    mocks.removeCellMember.mockResolvedValue({
      id: "membro-1",
      pessoaId: "pessoa-1",
      papel: "membro",
      ativo: false,
    });
    act(() => {
      root.render(
        h(ManageCellsPanel, {
          token: "tok-1",
          onToast: vi.fn(),
          onChanged: vi.fn(),
        }),
      );
    });
    await flushEffects();
    await selectCell();

    const removeBtn = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent?.includes("Remover"),
    ) as HTMLButtonElement;
    act(() => removeBtn.click());
    await flushEffects();

    const form = container.querySelector("form") as HTMLFormElement;
    await act(async () => {
      form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
      await Promise.resolve();
      await Promise.resolve();
    });
    await flushEffects();

    expect(mocks.removeCellMember).toHaveBeenCalledWith(
      "tok-1",
      "cell-1",
      "pessoa-1",
      undefined,
    );
  });

  it("não exibe botões de membro quando não há membros vinculados", async () => {
    mocks.fetchCellsFull.mockReset().mockResolvedValue({
      items: [cell()],
      page: 1,
      pageSize: 200,
      total: 1,
    });
    mocks.fetchCellMembros.mockReset().mockResolvedValue([]);
    mocks.fetchContacts.mockReset().mockResolvedValue({
      items: [],
      page: 1,
      pageSize: 200,
      total: 0,
    });
    act(() => {
      root.render(
        h(ManageCellsPanel, {
          token: "tok-1",
          onToast: vi.fn(),
          onChanged: vi.fn(),
        }),
      );
    });
    await flushEffects();
    await selectCell();

    const transferBtn = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent?.includes("Transferir"),
    );
    const removeBtn = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent?.includes("Remover"),
    );
    expect(transferBtn).toBeFalsy();
    expect(removeBtn).toBeFalsy();
  });
});
