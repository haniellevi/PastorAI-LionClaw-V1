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
  clearAuthedResponseCache: vi.fn(),
  promoteContact: vi.fn(),
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
    promoteContact: apiMock.promoteContact,
  };
});

vi.mock("@/lib/dashboard-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/dashboard-api")>();
  return {
    ...actual,
    fetchCells: apiMock.fetchCells,
    clearAuthedResponseCache: apiMock.clearAuthedResponseCache,
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
  return buttonWithText("Ver contato");
}

function vincularCelula(): HTMLButtonElement | undefined {
  return buttonWithText("Vincular célula");
}

function buttonWithText(text: string): HTMLButtonElement | undefined {
  return [...container.querySelectorAll("button")].find(
    (button) => button.textContent?.trim() === text,
  );
}

function openVisitantesTab() {
  const tab = [...container.querySelectorAll<HTMLButtonElement>("button")].find(
    (button) => button.textContent?.replace(/\s+/g, " ").trim().startsWith("Visitantes"),
  );
  act(() => tab?.click());
}

beforeEach(() => {
  authState.roles = ["admin"];
  authState.expireSession.mockClear();
  navigationMock.navigateToAdminRoute.mockReset();
  apiMock.fetchPipeline.mockReset();
  apiMock.fetchCells.mockReset();
  apiMock.clearAuthedResponseCache.mockReset();
  apiMock.promoteContact.mockReset();
  apiMock.promoteContact.mockResolvedValue({});
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

describe("GanharScreen — autorização para vincular célula", () => {
  const allowedRoleCases: Array<[label: string, roles: string[]]> = [
    ["admin", ["admin"]],
    ["pastor", ["pastor"]],
    ["papéis acumulados", ["membro", "lider_celula", "pastor"]],
  ];

  it.each(allowedRoleCases)("libera vínculo para %s", async (_label, roles) => {
    authState.roles = roles;
    await renderScreen();

    expect(vincularCelula()).toBeDefined();
    expect(apiMock.fetchCells).toHaveBeenCalledTimes(1);
    expect(apiMock.fetchCells).toHaveBeenCalledWith("tok-1");
  });

  it.each([
    "lider_g12",
    "lider_consol",
    "lider_celula",
    "lider_mult",
    "operador",
    "membro",
  ])("bloqueia vínculo para %s", async (role) => {
    authState.roles = [role];
    await renderScreen();

    expect(vincularCelula()).toBeUndefined();
    expect(apiMock.fetchCells).not.toHaveBeenCalled();
  });

  it("invalida o cache de células no retry somente quando autorizado", async () => {
    await renderScreen();

    act(() => {
      buttonWithText("Atualizar")?.dispatchEvent(
        new MouseEvent("click", { bubbles: true }),
      );
    });
    await flush();

    expect(apiMock.clearAuthedResponseCache).toHaveBeenCalledWith("tok-1", [
      "/pipeline?",
      "/cells?",
    ]);

    apiMock.clearAuthedResponseCache.mockClear();
    authState.roles = ["membro"];
    await renderScreen();

    act(() => {
      buttonWithText("Atualizar")?.dispatchEvent(
        new MouseEvent("click", { bubbles: true }),
      );
    });
    await flush();

    expect(apiMock.clearAuthedResponseCache).toHaveBeenCalledWith("tok-1", [
      "/pipeline?",
    ]);
  });

  it("remove o modal e não o restaura após revogação residual", async () => {
    apiMock.fetchCells.mockResolvedValue({
      items: [{ id: "c1", nome: "Célula Centro", liderId: "l1", ativo: true }],
      page: 1,
      pageSize: 200,
      total: 1,
    });
    await renderScreen();

    act(() => {
      vincularCelula()?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(container.querySelector('[role="dialog"]')).not.toBeNull();

    authState.roles = ["membro"];
    await renderScreen();

    expect(container.querySelector('[role="dialog"]')).toBeNull();
    expect(vincularCelula()).toBeUndefined();
    expect(apiMock.fetchCells).toHaveBeenCalledTimes(1);

    authState.roles = ["admin"];
    await renderScreen();

    expect(container.querySelector('[role="dialog"]')).toBeNull();
    expect(vincularCelula()).toBeDefined();
    expect(apiMock.fetchCells).toHaveBeenCalledTimes(2);
  });
});

describe("GanharScreen — autorização para promover no pipeline", () => {
  const visitor: Contact = {
    ...contact,
    tipo: "visitante",
    presencasCelula: 3,
  };

  it.each([
    ["admin", ["admin"]],
    ["pastor", ["pastor"]],
    ["lider_g12", ["lider_g12"]],
    ["lider_consol", ["lider_consol"]],
    ["papéis acumulados", ["membro", "lider_mult", "lider_consol"]],
  ] as Array<[string, string[]]>)("libera promoção para %s", async (_label, roles) => {
    authState.roles = roles;
    apiMock.fetchPipeline.mockResolvedValue({
      items: [visitor],
      page: 1,
      pageSize: 200,
      total: 1,
    });
    await renderScreen();
    openVisitantesTab();

    expect(buttonWithText("Promover")).toBeDefined();
    act(() => buttonWithText("Promover")?.click());
    await flush();

    expect(apiMock.promoteContact).toHaveBeenCalledWith("tok-1", "p1", "consolidar");
  });

  it.each(["membro", "lider_mult", "lider_celula", "operador"])(
    "oculta promoção para %s",
    async (role) => {
      authState.roles = [role];
      apiMock.fetchPipeline.mockResolvedValue({
        items: [visitor],
        page: 1,
        pageSize: 200,
        total: 1,
      });
      await renderScreen();
      openVisitantesTab();

      expect(buttonWithText("Promover")).toBeUndefined();
      expect(apiMock.promoteContact).not.toHaveBeenCalled();
    },
  );

  it("remove o CTA após revogação e não executa ação residual", async () => {
    authState.roles = ["lider_consol"];
    apiMock.fetchPipeline.mockResolvedValue({
      items: [visitor],
      page: 1,
      pageSize: 200,
      total: 1,
    });
    await renderScreen();
    openVisitantesTab();
    expect(buttonWithText("Promover")).toBeDefined();

    authState.roles = ["membro"];
    await renderScreen();
    openVisitantesTab();

    expect(buttonWithText("Promover")).toBeUndefined();
    expect(apiMock.promoteContact).not.toHaveBeenCalled();
  });
});
