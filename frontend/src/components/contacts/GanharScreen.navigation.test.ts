// @vitest-environment jsdom
import { act, createElement as h } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Contact } from "@/lib/contacts-api";

const authState = vi.hoisted(() => ({
  roles: ["admin"] as string[],
  expireSession: vi.fn(),
}));

const apiMock = vi.hoisted(() => ({
  fetchPipeline: vi.fn(),
  fetchCells: vi.fn(),
}));

const navigationMock = vi.hoisted(() => ({
  navigateToAdminRoute: vi.fn(),
}));

vi.mock("@/lib/auth-context", () => ({
  useAuth: () => ({
    token: "tok-1",
    user: { roles: authState.roles },
    expireSession: authState.expireSession,
  }),
}));

vi.mock("@/lib/contacts-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/contacts-api")>();
  return {
    ...actual,
    fetchPipeline: apiMock.fetchPipeline,
    linkContactCell: vi.fn(),
    promoteContact: vi.fn(),
  };
});

vi.mock("@/lib/dashboard-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/dashboard-api")>();
  return {
    ...actual,
    fetchCells: apiMock.fetchCells,
  };
});

vi.mock("@/lib/surface", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/surface")>();
  return {
    ...actual,
    navigateToAdminRoute: navigationMock.navigateToAdminRoute,
  };
});

const { GanharScreen } = await import("./GanharScreen");

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const contact: Contact = {
  id: "p1",
  nome: "Pessoa Teste",
  telefone: "5511987654321",
  email: null,
  genero: null,
  tipo: "contato",
  etapa: "ganhar",
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

async function flush() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

async function renderScreen() {
  act(() => root.render(h(GanharScreen)));
  await flush();
}

function verContato(): HTMLButtonElement | undefined {
  return [...container.querySelectorAll("button")].find(
    (button) => button.textContent?.trim() === "Ver contato",
  );
}

beforeEach(() => {
  authState.roles = ["admin"];
  authState.expireSession.mockClear();
  navigationMock.navigateToAdminRoute.mockReset();
  apiMock.fetchPipeline.mockResolvedValue({
    items: [contact],
    page: 1,
    pageSize: 200,
    total: 1,
  });
  apiMock.fetchCells.mockResolvedValue({
    items: [],
    page: 1,
    pageSize: 200,
    total: 0,
  });
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe("GanharScreen — detalhe administrativo", () => {
  it("o botão abre o contato uma vez na superfície admin", async () => {
    await renderScreen();

    act(() => {
      verContato()?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(navigationMock.navigateToAdminRoute).toHaveBeenCalledTimes(1);
    expect(navigationMock.navigateToAdminRoute).toHaveBeenCalledWith("contatos/p1");
  });

  it("o clique na linha usa o mesmo destino", async () => {
    await renderScreen();

    act(() => {
      container
        .querySelector("tbody tr")
        ?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(navigationMock.navigateToAdminRoute).toHaveBeenCalledTimes(1);
    expect(navigationMock.navigateToAdminRoute).toHaveBeenCalledWith("contatos/p1");
  });

  it("não oferece o atalho administrativo para papel não-admin", async () => {
    authState.roles = ["pastor"];
    await renderScreen();

    expect(verContato()).toBeUndefined();
    act(() => {
      container
        .querySelector("tbody tr")
        ?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(navigationMock.navigateToAdminRoute).not.toHaveBeenCalled();
  });
});
