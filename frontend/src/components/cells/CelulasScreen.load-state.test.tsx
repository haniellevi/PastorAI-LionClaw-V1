// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/dashboard-api";
import { CelulasScreen } from "./CelulasScreen";

const mocks = vi.hoisted(() => ({ fetchCellsFull: vi.fn(), expireSession: vi.fn() }));
vi.mock("@/lib/auth-context", () => ({
  useAuth: () => ({ token: "synthetic-token", user: { roles: ["admin"] }, expireSession: mocks.expireSession }),
}));
vi.mock("@/lib/cells-api", async () => ({
  ...await vi.importActual<typeof import("@/lib/cells-api")>("@/lib/cells-api"),
  fetchCellsFull: mocks.fetchCellsFull,
}));
vi.mock("@/lib/contacts-api", async () => ({
  ...await vi.importActual<typeof import("@/lib/contacts-api")>("@/lib/contacts-api"),
  fetchContacts: async () => ({ items: [], page: 1, pageSize: 200, total: 0 }),
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
    await act(async () => root.render(<CelulasScreen />));
    expect(container.querySelector('[role="alert"]')?.textContent).toContain("Leitura de células indisponível.");
    expect(container.querySelectorAll(".stat .val")).toHaveLength(0);
    expect(container.textContent).not.toContain("Nenhuma célula cadastrada.");

    mocks.fetchCellsFull.mockResolvedValue({ items: [], page: 1, pageSize: 200, total: 0 });
    const retry = Array.from(container.querySelectorAll("button")).find((button) => button.textContent?.includes("Tentar novamente"))!;
    await act(async () => retry.click());
    expect(container.querySelector('[role="alert"]')).toBeNull();
    expect(Array.from(container.querySelectorAll(".stat .val")).map((value) => value.textContent)).toEqual(["0", "0", "0", "0"]);
    expect(container.textContent).toContain("Nenhuma célula cadastrada.");
  });
});
