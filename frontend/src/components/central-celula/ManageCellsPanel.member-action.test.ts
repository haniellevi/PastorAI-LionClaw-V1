// @vitest-environment jsdom
import { act, createElement as h } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { CellSummary } from "@/lib/cells-api";

const mocks = vi.hoisted(() => ({
  fetchCellsFull: vi.fn(),
  fetchCellMembros: vi.fn(),
  upsertCell: vi.fn(),
  fetchContacts: vi.fn(),
  fetchTeam: vi.fn(),
  expireSession: vi.fn(),
}));

vi.mock("@/lib/auth-context", () => ({
  useAuth: () => ({ expireSession: mocks.expireSession }),
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

describe("ManageCellsPanel: adicionar Pessoa", () => {
  it.each([
    {
      label: "célula inativa",
      target: cell({ ativo: false }),
      reason: "Ative a célula antes de adicionar pessoas.",
    },
    {
      label: "célula sem líder",
      target: cell({ liderId: null }),
      reason: "Defina um líder antes de adicionar pessoas à célula.",
    },
  ])("desabilita a ação para $label e explica o motivo", async ({ target, reason }) => {
    mocks.fetchCellsFull.mockReset().mockResolvedValue({
      items: [target],
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

    const row = Array.from(container.querySelectorAll("button")).find((button) =>
      button.textContent?.includes("Célula Vida"),
    ) as HTMLButtonElement;
    act(() => row.click());
    await flushEffects();

    const add = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent?.trim() === "Adicionar à célula",
    ) as HTMLButtonElement;
    const reasonNode = container.querySelector(
      "#central-add-member-block-reason",
    ) as HTMLParagraphElement;

    expect(add.disabled).toBe(true);
    expect(add.getAttribute("aria-describedby")).toBe(
      "central-add-member-block-reason",
    );
    expect(reasonNode.getAttribute("role")).toBe("status");
    expect(reasonNode.textContent).toBe(reason);
  });

  it("mantém a ação disponível para célula ativa com líder", async () => {
    mocks.fetchCellsFull.mockReset().mockResolvedValue({
      items: [cell()],
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

    const row = Array.from(container.querySelectorAll("button")).find((button) =>
      button.textContent?.includes("Célula Vida"),
    ) as HTMLButtonElement;
    act(() => row.click());
    await flushEffects();

    const add = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent?.trim() === "Adicionar à célula",
    ) as HTMLButtonElement;
    expect(add.disabled).toBe(false);
    expect(add.hasAttribute("aria-describedby")).toBe(false);
  });
});
