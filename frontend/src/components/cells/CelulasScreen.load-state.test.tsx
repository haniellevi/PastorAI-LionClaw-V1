// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/dashboard-api";
import { CelulasScreen } from "./CelulasScreen";

const mocks = vi.hoisted(() => ({ fetchCellsFull: vi.fn(), fetchCellStats: vi.fn(), fetchContacts: vi.fn(), expireSession: vi.fn() }));
vi.mock("@/lib/auth-context", () => ({
  useAuth: () => ({ token: "synthetic-token", user: { roles: ["admin"] }, expireSession: mocks.expireSession }),
}));
vi.mock("@/lib/cells-api", async () => ({
  ...await vi.importActual<typeof import("@/lib/cells-api")>("@/lib/cells-api"),
  fetchCellsFull: mocks.fetchCellsFull,
}));
vi.mock("@/lib/lookup-api", async () => ({
  ...await vi.importActual<typeof import("@/lib/lookup-api")>("@/lib/lookup-api"),
  fetchCellListPage: mocks.fetchCellsFull,
  fetchCellStats: mocks.fetchCellStats,
}));
vi.mock("@/lib/contacts-api", async () => ({
  ...await vi.importActual<typeof import("@/lib/contacts-api")>("@/lib/contacts-api"),
  fetchContacts: mocks.fetchContacts,
}));
vi.mock("@/lib/church-cadastro-api", () => ({ fetchChurchCadastroCapability: async () => false }));

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
let container: HTMLDivElement;
let root: Root;
beforeEach(() => {
  vi.clearAllMocks();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(() => { act(() => root.unmount()); container.remove(); });

describe("Células: indicadores confirmados", () => {
  it("não converte falha inicial em quatro zeros e confirma ausência após retry", async () => {
    mocks.fetchCellsFull.mockRejectedValue(new ApiError(500, "Leitura de células indisponível."));
    mocks.fetchCellStats.mockResolvedValue(null);
    await act(async () => root.render(<CelulasScreen />));
    expect(container.querySelector('[role="alert"]')?.textContent).toContain("Leitura de células indisponível.");
    expect(container.querySelectorAll(".stat .val")).toHaveLength(0);
    expect(container.textContent).not.toContain("Nenhuma célula cadastrada.");

    mocks.fetchCellsFull.mockResolvedValue({ items: [], page: 1, pageSize: 200, total: 0 });
    mocks.fetchCellStats.mockResolvedValue({ total: 0, ativas: 0, semLider: 0, pessoasEmCelulas: 0 });
    const retry = Array.from(container.querySelectorAll("button")).find((button) => button.textContent?.includes("Tentar novamente"))!;
    await act(async () => retry.click());
    expect(container.querySelector('[role="alert"]')).toBeNull();
    expect(Array.from(container.querySelectorAll(".stat .val")).map((value) => value.textContent)).toEqual(["0", "0", "0", "0"]);
    expect(container.textContent).toContain("Nenhuma célula cadastrada.");
  });
  it("usa totais e contagens do servidor sem carregar toda a base de Pessoas", async () => {
    mocks.fetchCellsFull.mockResolvedValue({ items: [{ id: "c-201", nome: "Célula distante", liderId: "p-201", liderNome: "Líder distante", ativo: true, membros: 62, visitantes: 4 }], page: 1, pageSize: 25, total: 301 });
    mocks.fetchCellStats.mockResolvedValue({ total: 301, ativas: 299, semLider: 2, pessoasEmCelulas: 4000 });
    await act(async () => root.render(<CelulasScreen />));
    expect(container.querySelector(".ops-result-count")?.textContent).toContain("1 de 301 células");
    expect([...container.querySelectorAll(".cell-stat")].map((value) => value.textContent)).toEqual(["62", "4"]);
    expect([...container.querySelectorAll(".stat .val")].map((value) => value.textContent)).toEqual(["299", "2", "4000", "301"]);
    expect(container.textContent).toContain("Líder distante");
    expect(mocks.fetchContacts).not.toHaveBeenCalled();
  });
  it("pinta a página antes do fallback legado e restaura seus rótulos e contagens", async () => {
    let finishStats!: (summary: unknown) => void;
    const cell = { id: "c-200", nome: "Célula além200", liderId: null, ativo: true };
    mocks.fetchCellsFull.mockResolvedValue({ items: [cell], page: 1, pageSize: 25, total: 201 });
    mocks.fetchCellStats.mockImplementation(() => new Promise((resolve) => { finishStats = resolve; }));
    await act(async () => root.render(<CelulasScreen />));
    expect(container.querySelector('button[aria-label="Abrir célula Célula além200"]')).not.toBeNull();
    expect(container.querySelector(".ops-result-count")?.textContent).toContain("1 de 201 células");
    expect(container.querySelectorAll(".stat .val")).toHaveLength(0);
    await act(async () => finishStats({ total: 201, ativas: 200, semLider: 200, pessoasEmCelulas: 202,
      legacyCells: [{ ...cell, liderId: "p-200", liderNome: "Líder além200", membros: 201, visitantes: 1 }] }));
    expect(container.textContent).toContain("Líder além200");
    expect([...container.querySelectorAll(".cell-stat")].map((value) => value.textContent)).toEqual(["201", "1"]);
    expect([...container.querySelectorAll(".stat .val")].map((value) => value.textContent)).toEqual(["200", "200", "202", "201"]);
  });
});
