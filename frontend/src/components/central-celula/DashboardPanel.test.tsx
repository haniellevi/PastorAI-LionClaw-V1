// @vitest-environment jsdom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { CentralDashboard } from "@/lib/cell-central-api";

import { DashboardPanel } from "./DashboardPanel";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

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

const props = {
  dashboard,
  queue: [],
  loading: false,
  error: null,
  onRefresh: vi.fn(),
  onGoTo: vi.fn(),
};

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe("DashboardPanel", () => {
  it("não anuncia ausência sem dashboard confirmado, mesmo com a página de fila vazia", async () => {
    await act(async () =>
      root.render(<DashboardPanel {...props} dashboard={null} error="Resumo indisponível." />),
    );
    expect(container.textContent).toContain("Resumo indisponível.");
    expect(container.textContent).not.toContain("Nenhuma exceção aberta");
    expect(container.textContent).not.toContain("Nenhuma pendência na lista carregada.");
    expect(container.querySelector(".central-cards")).toBeNull();
  });

  it("não duplica multiplicações no resumo de pendências", async () => {
    await act(async () => root.render(<DashboardPanel {...props} />));
    expect(container.textContent).toContain("6 pendências pedem atenção");
  });
});
