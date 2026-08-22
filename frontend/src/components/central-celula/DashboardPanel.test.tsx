// @vitest-environment jsdom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SessionExpiredError } from "@/lib/api";
import type { CentralDashboard } from "@/lib/cell-central-api";

import { DashboardPanel } from "./DashboardPanel";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const mocks = vi.hoisted(() => ({
  expireSession: vi.fn(),
  getHealth: vi.fn(),
  getPendingReports: vi.fn(),
  getMultiplicacoesList: vi.fn(),
  listRequests: vi.fn(),
}));

vi.mock("@/lib/auth-context", () => ({
  useAuth: () => ({ expireSession: mocks.expireSession }),
}));

vi.mock("@/lib/cell-central-api", () => ({
  getHealth: mocks.getHealth,
  getPendingReports: mocks.getPendingReports,
}));

vi.mock("@/lib/cell-requests-api", () => ({
  listRequests: mocks.listRequests,
}));

vi.mock("@/lib/multiplicacoes-api", () => ({
  getMultiplicacoesList: mocks.getMultiplicacoesList,
}));

const dashboard: CentralDashboard = {
  relatorios_pendentes: 2,
  solicitacoes_aguardando: 3,
  celulas_com_alerta: 1,
  multiplicacoes_pendentes: 2,
  avisos_recentes: 0,
  materiais_recentes: 0,
};

let container: HTMLDivElement;
let root: Root;

function props(token: string) {
  return {
    token,
    dashboard,
    loading: false,
    error: null,
    onRetry: vi.fn(),
    onGoTo: vi.fn(),
  };
}

async function flush(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.getPendingReports.mockResolvedValue({ items: [], page: 1, page_size: 8 });
  mocks.listRequests.mockResolvedValue({ items: [], page: 1, pageSize: 8, total: 0 });
  mocks.getMultiplicacoesList.mockResolvedValue({ pendentes: [] });
  mocks.getHealth.mockResolvedValue({ cells: [] });
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe("DashboardPanel", () => {
  it("não duplica multiplicações no resumo de pendências", async () => {
    await act(async () => root.render(<DashboardPanel {...props("token-a")} />));
    await flush();

    expect(container.textContent).toContain("6 pendências pedem atenção");
  });

  it("expira a sessão quando uma leitura da fila rejeita o token", async () => {
    mocks.getPendingReports.mockRejectedValue(new SessionExpiredError());

    await act(async () => root.render(<DashboardPanel {...props("token-a")} />));
    await flush();

    expect(mocks.expireSession).toHaveBeenCalledTimes(1);
  });

  it("limpa dados anteriores enquanto carrega uma nova sessão", async () => {
    mocks.getPendingReports.mockResolvedValueOnce({
      items: [
        {
          reuniao_id: "r1",
          celula_id: "c1",
          celula_nome: "Célula da sessão A",
          lider_nome: "Líder A",
          data: "2026-08-10",
        },
      ],
      page: 1,
      page_size: 8,
    });

    await act(async () => root.render(<DashboardPanel {...props("token-a")} />));
    await flush();
    expect(container.textContent).toContain("Célula da sessão A");

    mocks.getPendingReports.mockReturnValueOnce(new Promise(() => {}));
    await act(async () => root.render(<DashboardPanel {...props("token-b")} />));

    expect(container.textContent).not.toContain("Célula da sessão A");
  });
});
