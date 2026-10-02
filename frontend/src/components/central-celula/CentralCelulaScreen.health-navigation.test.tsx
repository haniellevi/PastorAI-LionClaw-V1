// @vitest-environment jsdom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CentralCelulaScreen } from "./CentralCelulaScreen";

const mocks = vi.hoisted(() => ({
  expireSession: vi.fn(),
  getDashboard: vi.fn(),
  getHealth: vi.fn(),
  getPendingReports: vi.fn(),
  getMultiplicacoesList: vi.fn(),
  listRequests: vi.fn(),
}));

vi.mock("@/lib/auth-context", () => ({
  useAuth: () => ({ token: "synthetic-token", user: { roles: ["pastor"] }, expireSession: mocks.expireSession }),
}));
vi.mock("@/lib/cell-central-api", async () => ({
  ...await vi.importActual<typeof import("@/lib/cell-central-api")>("@/lib/cell-central-api"),
  getDashboard: mocks.getDashboard,
  getHealth: mocks.getHealth,
  getPendingReports: mocks.getPendingReports,
}));
vi.mock("@/lib/multiplicacoes-api", () => ({ getMultiplicacoesList: mocks.getMultiplicacoesList }));
vi.mock("@/lib/cell-requests-api", () => ({ listRequests: mocks.listRequests }));
vi.mock("@/lib/church-cadastro-api", () => ({ fetchChurchCadastroCapability: async () => false }));
vi.mock("@/lib/cells-api", async () => ({
  ...await vi.importActual<typeof import("@/lib/cells-api")>("@/lib/cells-api"),
  fetchCellsFull: async () => ({ items: [], total: 0 }),
}));
vi.mock("@/lib/contacts-api", async () => ({
  ...await vi.importActual<typeof import("@/lib/contacts-api")>("@/lib/contacts-api"),
  fetchContacts: async () => ({ items: [], total: 0 }),
}));
vi.mock("@/lib/dashboard-api", async () => ({
  ...await vi.importActual<typeof import("@/lib/dashboard-api")>("@/lib/dashboard-api"),
  fetchTeam: async () => ({ items: [], total: 0 }),
}));
vi.mock("./MultiplicationsList", () => ({ MultiplicationsList: () => null }));
vi.mock("./PendingReportsList", () => ({ PendingReportsList: () => null }));
vi.mock("./RequestsPanel", () => ({ RequestsPanel: () => <p>Decisões de solicitações</p> }));

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

async function render() {
  await act(async () => {
    root.render(<CentralCelulaScreen />);
    await Promise.resolve();
    await Promise.resolve();
  });
}

async function click(text: string) {
  const button = Array.from(container.querySelectorAll("button")).find((item) => item.textContent?.includes(text));
  expect(button, `ação ${text}`).toBeDefined();
  await act(async () => button!.click());
}

function healthDisclosure() {
  return Array.from(container.querySelectorAll("details")).find((item) => item.querySelector("summary")?.textContent === "Saúde e multiplicações")!;
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.getDashboard.mockResolvedValue({ relatorios_pendentes: 0, solicitacoes_aguardando: 0, celulas_com_alerta: 1, multiplicacoes_pendentes: 0, avisos_recentes: 0, materiais_recentes: 0 });
  mocks.getHealth.mockResolvedValue({ cells: [{ celula_id: "synthetic-cell", celula_nome: "Célula de teste em atenção", status: "atencao", vermelhos: 0, alertas: 1, sinais: [] }] });
  mocks.getPendingReports.mockResolvedValue({ items: [] });
  mocks.getMultiplicacoesList.mockResolvedValue({ pendentes: [] });
  mocks.listRequests.mockResolvedValue({ items: [] });
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe("Central: destino de saúde", () => {
  it("revela e foca a saúde ao abrir a pendência, permitindo fechar e reabrir pelo atalho", async () => {
    await render();
    await click("Ver saúde");
    expect(healthDisclosure().open).toBe(true);
    expect(document.activeElement).toBe(healthDisclosure().querySelector("summary"));
    expect(container.querySelector('[aria-label="Saúde das células"]')?.textContent).toContain("Célula de teste em atenção");

    healthDisclosure().open = false;
    await click("Hoje");
    await click("Ver saúde");
    expect(healthDisclosure().open).toBe(true);
    expect(document.activeElement).toBe(healthDisclosure().querySelector("summary"));
  });

  it("não revela o panorama ao navegar manualmente ou por relatório pendente", async () => {
    mocks.getPendingReports.mockResolvedValue({ items: [{ reuniao_id: "synthetic-meeting", celula_id: "synthetic-cell", celula_nome: "Célula com relatório", lider_nome: "Líder fictício", data: "2026-09-30" }] });
    await render();
    await click("Gerenciar células");
    expect(healthDisclosure().open).toBe(false);
    await click("Hoje");
    await click("Ver relatórios");
    expect(healthDisclosure().open).toBe(false);
  });

  it("mantém uma multiplicação no destino de decisão", async () => {
    mocks.getMultiplicacoesList.mockResolvedValue({ pendentes: [{ id: "synthetic-request", created_at: "2026-09-30T12:00:00Z" }] });
    await render();
    await click("Decidir");
    expect(container.textContent).toContain("Decisões de solicitações");
    expect(container.querySelector("details")).toBeNull();
  });
});
