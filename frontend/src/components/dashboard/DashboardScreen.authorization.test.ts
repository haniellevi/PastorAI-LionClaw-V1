// @vitest-environment jsdom
import { act, createElement as h } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { WorkItem } from "@/lib/dashboard-api";

const authState = vi.hoisted(() => ({
  roles: ["admin"] as string[],
  expireSession: vi.fn(),
}));

const apiMock = vi.hoisted(() => ({
  fetchWorkQueue: vi.fn(),
  fetchTeamLookup: vi.fn(),
  fetchCells: vi.fn(),
  fetchOverview: vi.fn(),
  clearAuthedResponseCache: vi.fn(),
  linkCell: vi.fn(),
  queueAction: vi.fn(),
  queueFonovisita: vi.fn(),
  sendInternalMessage: vi.fn(),
}));

vi.mock("@/lib/auth-context", () => ({
  useAuth: () => ({
    token: "tok-1",
    user: {
      appUserId: "u1",
      nome: "Pessoa Teste",
      roles: authState.roles,
    },
    expireSession: authState.expireSession,
  }),
}));

vi.mock("@/lib/permissions-context", () => ({
  usePermissions: () => ({ matrix: {} }),
}));

vi.mock("@/lib/use-hash-route", () => ({
  useHashRoute: () => ["dashboard", vi.fn()],
}));

vi.mock("@/lib/dashboard-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/dashboard-api")>();
  return {
    ...actual,
    fetchWorkQueue: apiMock.fetchWorkQueue,
    fetchTeamLookup: apiMock.fetchTeamLookup,
    fetchCells: apiMock.fetchCells,
    fetchOverview: apiMock.fetchOverview,
    clearAuthedResponseCache: apiMock.clearAuthedResponseCache,
    linkCell: apiMock.linkCell,
    queueAction: apiMock.queueAction,
    queueFonovisita: apiMock.queueFonovisita,
    sendInternalMessage: apiMock.sendInternalMessage,
  };
});

const { DashboardScreen } = await import("./DashboardScreen");

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const workItem: WorkItem = {
  id: "q1",
  tipo: "visitante",
  titulo: "Conectar Pessoa Teste a uma célula",
  contexto: "Nova pessoa",
  status: "pendente",
  pessoaId: "p1",
  responsavelId: null,
  prioridade: 1,
  canMessage: true,
  prazo: new Date(Date.now() + 3600e3).toISOString(),
};

let container: HTMLDivElement;
let root: Root;

async function flush() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

async function renderScreen() {
  act(() => root.render(h(DashboardScreen)));
  await flush();
}

function buttonWithText(text: string): HTMLButtonElement | undefined {
  return [...container.querySelectorAll("button")].find(
    (button) => button.textContent?.replace(/\s+/g, " ").trim() === text,
  );
}

beforeEach(() => {
  authState.roles = ["admin"];
  authState.expireSession.mockClear();
  for (const mock of Object.values(apiMock)) mock.mockReset();

  apiMock.fetchWorkQueue.mockResolvedValue({
    items: [workItem],
    page: 1,
    pageSize: 100,
    total: 1,
  });
  apiMock.fetchTeamLookup.mockResolvedValue({
    items: [],
    page: 1,
    pageSize: 100,
    total: 0,
  });
  apiMock.fetchCells.mockResolvedValue({
    items: [{ id: "c1", nome: "Célula Centro", liderId: "l1", ativo: true }],
    page: 1,
    pageSize: 100,
    total: 1,
  });
  apiMock.fetchOverview.mockResolvedValue(null);
  apiMock.linkCell.mockResolvedValue(undefined);

  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe("DashboardScreen — autorização para conectar à célula", () => {
  const allowedRoleCases: Array<[label: string, roles: string[]]> = [
    ["admin", ["admin"]],
    ["pastor", ["pastor"]],
    ["papéis acumulados", ["membro", "lider_celula", "pastor"]],
  ];

  it.each(allowedRoleCases)("libera a capacidade para %s", async (_label, roles) => {
    authState.roles = roles;
    await renderScreen();

    expect(apiMock.fetchCells).toHaveBeenCalledTimes(1);
    expect(apiMock.fetchCells).toHaveBeenCalledWith("tok-1");
    expect(buttonWithText("Conectar à célula")).toBeDefined();
  });

  const blockedRoleCases: Array<
    [role: string, keepsQueue: boolean, canAssignQueue: boolean]
  > = [
    ["lider_g12", true, true],
    ["lider_consol", true, true],
    ["lider_celula", true, false],
    ["lider_mult", true, false],
    ["operador", false, false],
    ["membro", false, false],
  ];

  it.each(blockedRoleCases)(
    "bloqueia a capacidade para %s",
    async (role, keepsQueue, canAssignQueue) => {
      authState.roles = [role];
      await renderScreen();

      expect(apiMock.fetchCells).not.toHaveBeenCalled();
      expect(apiMock.fetchTeamLookup).toHaveBeenCalledTimes(canAssignQueue ? 1 : 0);
      expect(buttonWithText("Conectar à célula")).toBeUndefined();
      if (keepsQueue) {
        expect(buttonWithText("Assumir")).toBeDefined();
        expect(buttonWithText("Atribuir") !== undefined).toBe(canAssignQueue);
        expect(buttonWithText("Mensagem")).toBeDefined();
      }
    },
  );

  it.each([
    ["admin", ["admin"], true, true],
    ["líder de célula", ["lider_celula"], false, false],
  ] as Array<
    [label: string, roles: string[], includesCells: boolean, includesTeam: boolean]
  >)(
    "invalida o cache correto no retry para %s",
    async (_label, roles, includesCells, includesTeam) => {
      authState.roles = roles;
      await renderScreen();

      act(() => {
        buttonWithText("Atualizar")?.dispatchEvent(
          new MouseEvent("click", { bubbles: true }),
        );
      });
      await flush();

      const expectedPaths = [
        "/work-queue?",
        ...(includesTeam ? ["/team/lookup?"] : []),
        ...(includesCells ? ["/cells?"] : []),
        "/dashboard/overview",
      ];
      expect(apiMock.clearAuthedResponseCache).toHaveBeenCalledWith(
        "tok-1",
        expectedPaths,
      );
    },
  );

  it("remove e não restaura modal residual após revogação", async () => {
    await renderScreen();

    act(() => {
      buttonWithText("Conectar à célula")?.dispatchEvent(
        new MouseEvent("click", { bubbles: true }),
      );
    });
    expect(container.querySelector('[role="dialog"]')).not.toBeNull();

    authState.roles = ["lider_celula"];
    await renderScreen();

    expect(container.querySelector('[role="dialog"]')).toBeNull();
    expect(buttonWithText("Conectar à célula")).toBeUndefined();
    expect(apiMock.fetchCells).toHaveBeenCalledTimes(1);
    expect(apiMock.linkCell).not.toHaveBeenCalled();

    authState.roles = ["admin"];
    await renderScreen();

    expect(container.querySelector('[role="dialog"]')).toBeNull();
    expect(buttonWithText("Conectar à célula")).toBeDefined();
    expect(apiMock.fetchCells).toHaveBeenCalledTimes(2);
  });
});

describe("DashboardScreen — autorização para atribuir fila", () => {
  const allowedRoleCases: Array<[label: string, roles: string[]]> = [
    ["admin", ["admin"]],
    ["pastor", ["pastor"]],
    ["líder G12", ["lider_g12"]],
    ["líder de consolidação", ["lider_consol"]],
    ["papéis acumulados", ["membro", "lider_celula", "lider_consol"]],
  ];

  it.each(allowedRoleCases)("libera atribuição para %s", async (_label, roles) => {
    authState.roles = roles;
    await renderScreen();

    expect(buttonWithText("Atribuir")).toBeDefined();
    expect(buttonWithText("Assumir")).toBeDefined();
  });

  it.each([
    ["lider_celula", true],
    ["lider_mult", true],
    ["operador", false],
    ["membro", false],
  ] as Array<[role: string, keepsQueue: boolean]>)(
    "bloqueia atribuição para %s",
    async (role, keepsQueue) => {
      authState.roles = [role];
      await renderScreen();

      expect(buttonWithText("Atribuir")).toBeUndefined();
      if (keepsQueue) expect(buttonWithText("Assumir")).toBeDefined();
      expect(apiMock.queueAction).not.toHaveBeenCalled();
    },
  );

  it("remove e não restaura modal assign após revogação", async () => {
    authState.roles = ["lider_g12"];
    await renderScreen();

    act(() => {
      buttonWithText("Atribuir")?.dispatchEvent(
        new MouseEvent("click", { bubbles: true }),
      );
    });
    expect(container.querySelector('[role="dialog"]')).not.toBeNull();

    authState.roles = ["lider_celula"];
    await renderScreen();

    expect(container.querySelector('[role="dialog"]')).toBeNull();
    expect(buttonWithText("Atribuir")).toBeUndefined();
    expect(buttonWithText("Assumir")).toBeDefined();
    expect(apiMock.queueAction).not.toHaveBeenCalled();

    authState.roles = ["lider_g12"];
    await renderScreen();

    expect(container.querySelector('[role="dialog"]')).toBeNull();
    expect(buttonWithText("Atribuir")).toBeDefined();
  });

  it("picker mostra somente destinos elegíveis e nunca exibe e-mail", async () => {
    apiMock.fetchTeamLookup.mockResolvedValue({
      items: [
        {
          usuarioId: "u-pastor",
          nome: "Pastor Elegível",
          email: "privado@example.com",
          status: null,
          papeis: ["pastor"],
          pessoaId: "p-pastor",
          tiposFila: ["visitante", "atendimento", "relatorio", "conectar_celula", "fonovisita"],
        },
        {
          usuarioId: "u-membro",
          nome: "Membro Inelegível",
          email: "nao-exibir@example.com",
          status: null,
          papeis: ["membro"],
          pessoaId: "p-membro",
          tiposFila: [],
        },
      ],
      page: 1,
      pageSize: 100,
      total: 2,
    });
    await renderScreen();

    act(() => buttonWithText("Atribuir")?.click());

    const pickerText = container.querySelector(".dh-picker")?.textContent ?? "";
    expect(pickerText).toContain("Pastor Elegível");
    expect(pickerText).toContain("Pastor");
    expect(pickerText).not.toContain("Membro Inelegível");
    expect(pickerText).not.toContain("@example.com");
  });
});
