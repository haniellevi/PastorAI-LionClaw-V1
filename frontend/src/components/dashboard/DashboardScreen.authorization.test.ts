// @vitest-environment jsdom
import { act, createElement as h } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { WorkItem } from "@/lib/dashboard-api";

const authState = vi.hoisted(() => ({
  roles: ["admin"] as string[],
  nome: "Pessoa Teste",
  chatNome: null as string | null,
  expireSession: vi.fn(),
}));

const apiMock = vi.hoisted(() => ({
  fetchWorkQueuePage: vi.fn(),
  fetchRemainingWorkQueuePages: vi.fn(),
  fetchTeamLookup: vi.fn(),
  fetchCells: vi.fn(),
  fetchOverview: vi.fn(),
  clearAuthedResponseCache: vi.fn(),
  linkCell: vi.fn(),
  queueAction: vi.fn(),
  queueFonovisita: vi.fn(),
  sendInternalMessage: vi.fn(),
  fetchEvents: vi.fn(),
  getLedCellsTodayContext: vi.fn(),
  getNextMeeting: vi.fn(),
  getMyNotices: vi.fn(),
  listNotices: vi.fn(),
}));

vi.mock("@/lib/auth-context", () => ({
  useAuth: () => ({
    token: "tok-1",
    user: {
      appUserId: "u1",
      nome: authState.nome,
      chatNome: authState.chatNome,
      roles: authState.roles,
    },
    expireSession: authState.expireSession,
  }),
}));

vi.mock("@/lib/permissions-context", () => ({
  usePermissions: () => ({ matrix: undefined }),
}));

vi.mock("@/lib/use-hash-route", () => ({
  useHashRoute: () => ["dashboard", vi.fn()],
}));

vi.mock("@/lib/dashboard-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/dashboard-api")>();
  return {
    ...actual,
    fetchWorkQueuePage: apiMock.fetchWorkQueuePage,
    fetchRemainingWorkQueuePages: apiMock.fetchRemainingWorkQueuePages,
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

vi.mock("@/lib/events-api", () => ({
  fetchUpcomingEvents: apiMock.fetchEvents,
}));

vi.mock("@/lib/cells-api", () => ({
  getLedCellsTodayContext: apiMock.getLedCellsTodayContext,
  getNextMeeting: apiMock.getNextMeeting,
}));

vi.mock("@/lib/cell-notices-api", () => ({
  getMyNotices: apiMock.getMyNotices,
  listNotices: apiMock.listNotices,
}));

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

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((onResolve, onReject) => {
    resolve = onResolve;
    reject = onReject;
  });
  return { promise, resolve, reject };
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
  authState.nome = "Pessoa Teste";
  authState.chatNome = null;
  authState.expireSession.mockClear();
  for (const mock of Object.values(apiMock)) mock.mockReset();

  apiMock.fetchWorkQueuePage.mockResolvedValue({
    items: [workItem],
    page: 1,
    pageSize: 25,
    total: 1,
  });
  apiMock.fetchRemainingWorkQueuePages.mockResolvedValue({ items: [], total: 1 });
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
  apiMock.fetchOverview.mockResolvedValue({
    scope: "igreja",
    total: 0,
    decisoesJesus: 0,
    celulasAtivas: 0,
    lideresCelula: 0,
    semInteresse: 0,
    porTipo: {},
    porEtapa: {},
  });
  apiMock.fetchEvents.mockResolvedValue({
    items: [],
    page: 1,
    pageSize: 200,
    total: 0,
  });
  apiMock.getNextMeeting.mockResolvedValue({ meeting: null });
  apiMock.getLedCellsTodayContext.mockResolvedValue({ cells: [], meeting: null });
  apiMock.getMyNotices.mockResolvedValue([]);
  apiMock.listNotices.mockResolvedValue({
    items: [],
    page: 1,
    page_size: 50,
    total: 0,
  });
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
    ["lider_mult", false, false],
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

describe("DashboardScreen — navegação semântica", () => {
  it("prefere o nome de conversa e remove títulos pastorais da saudação", async () => {
    authState.nome = "Pastor Daniel Oliveira";
    authState.chatNome = "Pr. Daniel";

    await renderScreen();

    expect(container.querySelector(".dh-title")?.textContent).toMatch(
      /^(Bom dia|Boa tarde|Boa noite), Daniel$/,
    );
  });

  it("expõe resumo, Jornada e agente como links hash reais", async () => {
    authState.roles = ["admin"];
    await renderScreen();
    await flush();

    expect(container.querySelector('a.dh-summary-row[href="#ganhar"]')).not.toBeNull();
    expect(container.querySelector('a.dh-journey-row[href="#ganhar"]')).not.toBeNull();
    expect(container.querySelector('a.dh-journey-cta[href="#agente"]')).not.toBeNull();
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
    ["lider_mult", false],
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

  it("move o foco para a fila mesmo se o modal fechar durante a atribuição", async () => {
    const assignment = deferred<{ status: string; responsavelId: string }>();
    apiMock.fetchWorkQueuePage.mockResolvedValue({
      items: [
        { ...workItem, responsavelId: "u1", status: "assumido" },
        {
          ...workItem,
          id: "q2",
          titulo: "Outra ação sob cuidado",
          responsavelId: "u1",
          status: "assumido",
        },
      ],
      page: 1,
      pageSize: 25,
      total: 2,
    });
    apiMock.fetchTeamLookup.mockResolvedValue({
      items: [
        {
          usuarioId: "u2",
          nome: "Pastor Dois",
          email: "pastor2@example.com",
          status: null,
          papeis: ["pastor"],
          pessoaId: "p2",
          tiposFila: [
            "visitante",
            "atendimento",
            "relatorio",
            "conectar_celula",
            "fonovisita",
          ],
        },
      ],
      page: 1,
      pageSize: 100,
      total: 1,
    });
    apiMock.queueAction.mockReturnValue(assignment.promise);
    await renderScreen();

    act(() => buttonWithText("Meus")?.click());
    act(() =>
      (
        container.querySelector(
          '[aria-label="Atribuir responsável: Conectar Pessoa Teste a uma célula"]',
        ) as HTMLButtonElement | null
      )?.click(),
    );
    act(() =>
      (container.querySelector(".dh-picker-row") as HTMLButtonElement | null)?.click(),
    );
    await flush();
    act(() =>
      (container.querySelector(".ds-dialog-close") as HTMLButtonElement | null)?.click(),
    );
    expect(container.querySelector('[role="dialog"]')).toBeNull();
    const assignmentButtons = [
      ...container.querySelectorAll<HTMLButtonElement>(
        '[aria-label^="Atribuir responsável:"]',
      ),
    ];
    expect(assignmentButtons).toHaveLength(2);
    expect(assignmentButtons.every((button) => button.disabled)).toBe(true);
    act(() => assignmentButtons[1]?.click());
    expect(container.querySelector('[role="dialog"]')).toBeNull();

    assignment.resolve({ status: "assumido", responsavelId: "u2" });
    await flush();

    expect(container.textContent).not.toContain(workItem.titulo);
    expect(container.textContent).toContain("Outra ação sob cuidado");
    expect(document.activeElement).toBe(
      container.querySelector("#dashboard-queue-title"),
    );
  });
});

describe("DashboardScreen — composição por responsabilidades", () => {
  it("anuncia a atualização e expõe o estado ocupado no botão", async () => {
    const firstPage = deferred<{
      items: WorkItem[];
      page: number;
      pageSize: number;
      total: number;
    }>();
    apiMock.fetchWorkQueuePage.mockReturnValue(firstPage.promise);

    await renderScreen();

    expect(buttonWithText("Atualizar")?.getAttribute("aria-busy")).toBe("true");
    expect(container.querySelector('[role="status"]')?.textContent).toContain(
      "Atualizando as informações de hoje.",
    );

    firstPage.resolve({ items: [workItem], page: 1, pageSize: 25, total: 1 });
    await flush();

    expect(buttonWithText("Atualizar")?.hasAttribute("aria-busy")).toBe(false);
    expect(container.querySelector('[role="status"]')?.textContent).toContain(
      "1 ação disponível.",
    );
  });

  it("mostra Agenda, próxima reunião e avisos reais ao membro sem carregar fila", async () => {
    authState.roles = ["membro"];
    apiMock.fetchEvents.mockResolvedValue({
      items: [
        {
          id: "e1",
          titulo: "Culto de celebração",
          data: "2999-08-12",
          hora: "20:00",
          descricao: null,
          googleEventId: null,
          sincronizado: false,
          status: "confirmado",
        },
      ],
      page: 1,
      pageSize: 200,
      total: 1,
    });
    apiMock.getNextMeeting.mockResolvedValue({
      meeting: {
        id: "r1",
        celula_id: "c1",
        data: "2999-08-13",
        hora: "19:30",
        local: "Bairro Centro",
        tema: "Uma vida com propósito",
        minha_presenca: "nao_confirmou",
      },
    });
    apiMock.getMyNotices.mockResolvedValue([
      {
        id: "a1",
        origem: "igreja",
        escopo: "igreja",
        titulo: "Mutirão solidário",
        conteudo: "Inscrições abertas.",
        publicado_em: "2026-08-11T09:00:00Z",
      },
    ]);

    await renderScreen();

    expect(container.textContent).toContain("Para você");
    expect(container.textContent).toContain("Culto de celebração");
    expect(container.textContent).toContain("Uma vida com propósito");
    expect(container.textContent).toContain("Mutirão solidário");
    expect(container.textContent?.toLowerCase()).not.toContain("fila pastoral");
    expect(apiMock.fetchWorkQueuePage).not.toHaveBeenCalled();
    expect(apiMock.fetchOverview).not.toHaveBeenCalled();
    expect(apiMock.fetchEvents).toHaveBeenCalledWith("tok-1");
    expect(apiMock.getNextMeeting).toHaveBeenCalledWith("tok-1");
    expect(apiMock.getMyNotices).toHaveBeenCalledWith("tok-1");
    expect(apiMock.getLedCellsTodayContext).not.toHaveBeenCalled();
    expect(apiMock.listNotices).not.toHaveBeenCalled();
  });

  it("dá ao operador seus atalhos reais sem tratá-lo como membro ou liderança", async () => {
    authState.roles = ["operador"];

    await renderScreen();

    expect(container.textContent).toContain("Seus atendimentos");
    expect(container.textContent).toContain("Conversas");
    expect(container.textContent).toContain("Ganhar");
    expect(container.textContent).not.toContain("Bem-vindo(a) à sua igreja");
    expect(apiMock.fetchWorkQueuePage).not.toHaveBeenCalled();
    expect(apiMock.fetchEvents).not.toHaveBeenCalled();
    expect(apiMock.getNextMeeting).not.toHaveBeenCalled();
    expect(apiMock.getMyNotices).not.toHaveBeenCalled();
    expect(apiMock.listNotices).toHaveBeenCalledWith("tok-1");
  });

  it("não carrega fila vazia para líder de multiplicação", async () => {
    authState.roles = ["lider_mult"];

    await renderScreen();

    expect(container.textContent).toContain("Sua responsabilidade: Multiplicação");
    expect(container.textContent).toContain("Jornada G12");
    expect(container.textContent).toContain("Enviar");
    expect(apiMock.fetchWorkQueuePage).not.toHaveBeenCalled();
    expect(apiMock.fetchOverview).not.toHaveBeenCalled();
  });

  it.each([
    ["admin", "Ações da igreja", false],
    ["pastor", "Fila pastoral da igreja", true],
    ["lider_g12", "Ações da igreja sob sua responsabilidade", false],
    ["lider_consol", "Ações de consolidação", false],
    ["lider_celula", "Ações sob seus cuidados", false],
  ] as const)("usa linguagem adequada para %s", async (role, heading, maySayPastoral) => {
    authState.roles = [role];

    await renderScreen();

    expect(container.textContent).toContain(heading);
    if (!maySayPastoral) {
      expect(container.textContent?.toLowerCase()).not.toContain("fila pastoral");
    }
  });

  it("compõe papéis acumulados em uma única fila e preserva os demais espaços", async () => {
    authState.roles = ["membro", "lider_celula", "lider_consol"];

    await renderScreen();

    expect(container.textContent).toContain("Ações de consolidação");
    expect(container.textContent).toContain("Minha Célula");
    expect(container.textContent).toContain("Consolidar");
    expect(container.querySelectorAll(".dh-item")).toHaveLength(1);
    expect(apiMock.fetchWorkQueuePage).toHaveBeenCalledTimes(1);
    expect(apiMock.fetchTeamLookup).toHaveBeenCalledTimes(1);
    expect(apiMock.getLedCellsTodayContext).toHaveBeenCalledWith("tok-1");
    expect(apiMock.getNextMeeting).not.toHaveBeenCalled();
  });

  it("usa a célula B liderada, não a célula A onde o líder é membro", async () => {
    authState.roles = ["membro", "lider_celula"];
    apiMock.getNextMeeting.mockResolvedValue({
      meeting: {
        id: "r-a",
        celula_id: "cell-a",
        data: "2999-08-13",
        hora: "18:00",
        local: null,
        tema: "Reunião da célula A",
        minha_presenca: "nao_confirmou",
      },
    });
    apiMock.getLedCellsTodayContext.mockResolvedValue({
      cells: [{ id: "cell-b", nome: "Célula B" }],
      meeting: {
        id: "r-b",
        celula_id: "cell-b",
        data: "2999-08-14",
        hora: "19:30",
        local: null,
        tema: "Célula B: Cuidado que transforma",
        minha_presenca: "nao_confirmou",
      },
    });
    apiMock.listNotices.mockResolvedValue({
      items: [
        {
          id: "church",
          origem: "igreja",
          escopo: "igreja",
          celula_id: null,
          titulo: "Aviso da igreja",
          conteudo: "Para todos.",
          ativo: true,
          publicado_em: "2026-08-11T10:00:00Z",
          notificado_em: null,
        },
        {
          id: "notice-a",
          origem: "celula",
          escopo: "celula",
          celula_id: "cell-a",
          titulo: "Aviso da célula A",
          conteudo: "Não pertence ao contexto liderado.",
          ativo: true,
          publicado_em: "2026-08-11T09:00:00Z",
          notificado_em: null,
        },
        {
          id: "notice-b",
          origem: "celula",
          escopo: "celula",
          celula_id: "cell-b",
          titulo: "Aviso da célula B",
          conteudo: "Responsabilidade do líder.",
          ativo: true,
          publicado_em: "2026-08-11T08:00:00Z",
          notificado_em: null,
        },
      ],
      page: 1,
      page_size: 50,
      total: 3,
    });

    await renderScreen();

    expect(container.textContent).toContain("Célula B: Cuidado que transforma");
    expect(container.textContent).toContain("Aviso da igreja");
    expect(container.textContent).toContain("Aviso da célula B");
    expect(container.textContent).not.toContain("Reunião da célula A");
    expect(container.textContent).not.toContain("Aviso da célula A");
    expect(apiMock.getLedCellsTodayContext).toHaveBeenCalledWith("tok-1");
    expect(apiMock.getNextMeeting).not.toHaveBeenCalled();
    expect(apiMock.getMyNotices).not.toHaveBeenCalled();
  });

  it("não cai no vínculo de membro quando o líder ainda não tem célula liderada", async () => {
    authState.roles = ["lider_celula"];
    apiMock.getLedCellsTodayContext.mockResolvedValue({ cells: [], meeting: null });

    await renderScreen();

    expect(container.textContent).toContain("Nenhuma próxima reunião planejada.");
    expect(apiMock.getLedCellsTodayContext).toHaveBeenCalledWith("tok-1");
    expect(apiMock.getNextMeeting).not.toHaveBeenCalled();
    expect(apiMock.getMyNotices).not.toHaveBeenCalled();
  });

  it("mantém três ações na primeira visão e permite expandir a fila", async () => {
    apiMock.fetchWorkQueuePage.mockResolvedValue({
      items: Array.from({ length: 5 }, (_, index) => ({
        ...workItem,
        id: `q${index + 1}`,
        titulo: `Ação ${index + 1}`,
      })),
      page: 1,
      pageSize: 25,
      total: 5,
    });

    await renderScreen();

    expect(container.querySelectorAll(".dh-item")).toHaveLength(3);
    const expand = buttonWithText("Ver todas as 5 ações");
    expect(expand).toBeDefined();

    act(() => expand?.click());

    expect(container.querySelectorAll(".dh-item")).toHaveLength(5);
    expect(buttonWithText("Mostrar menos")).toBeDefined();
  });

  it("libera a primeira página e preserva a expansão durante a hidratação", async () => {
    const firstItems = Array.from({ length: 5 }, (_, index) => ({
      ...workItem,
      id: `first-${index + 1}`,
      titulo: `Primeira ${index + 1}`,
    }));
    const restItems = Array.from({ length: 3 }, (_, index) => ({
      ...workItem,
      id: `rest-${index + 1}`,
      titulo: `Restante ${index + 1}`,
    }));
    const remainder = deferred<{ items: WorkItem[]; total: number }>();
    apiMock.fetchWorkQueuePage.mockResolvedValue({
      items: firstItems,
      page: 1,
      pageSize: 25,
      total: 8,
    });
    apiMock.fetchRemainingWorkQueuePages.mockReturnValue(remainder.promise);

    await renderScreen();

    expect(buttonWithText("Assumir")).toBeDefined();
    expect(container.querySelectorAll(".dh-item")).toHaveLength(3);
    expect(container.textContent).toContain("5 de 8 ações carregadas");
    expect(container.textContent).toContain("Você tem 8 ações");
    const expand = buttonWithText("Ver 5 ações já carregadas");
    expect(expand).toBeDefined();

    act(() => expand?.click());
    expect(container.querySelectorAll(".dh-item")).toHaveLength(5);

    remainder.resolve({ items: restItems, total: 8 });
    await flush();

    expect(container.querySelectorAll(".dh-item")).toHaveLength(8);
    expect(buttonWithText("Mostrar menos")).toBeDefined();
    expect(container.textContent).not.toContain("Completando a fila");
  });

  it("não mostra vazio falso no filtro Meus enquanto faltam páginas", async () => {
    const remainder = deferred<{ items: WorkItem[]; total: number }>();
    apiMock.fetchWorkQueuePage.mockResolvedValue({
      items: [{ ...workItem, id: "other", responsavelId: "u2" }],
      page: 1,
      pageSize: 25,
      total: 2,
    });
    apiMock.fetchRemainingWorkQueuePages.mockReturnValue(remainder.promise);

    await renderScreen();
    act(() => buttonWithText("Meus")?.click());

    expect(container.textContent).toContain("Conferindo suas ações.");
    expect(container.textContent).not.toContain("Fila zerada.");

    remainder.resolve({
      items: [
        {
          ...workItem,
          id: "mine",
          titulo: "Minha ação encontrada depois",
          responsavelId: "u1",
        },
      ],
      total: 2,
    });
    await flush();

    expect(container.textContent).toContain("Minha ação encontrada depois");
    expect(container.textContent).not.toContain("Conferindo suas ações.");
  });

  it("mantém a primeira página e informa total parcial se a hidratação falhar", async () => {
    const firstItems = Array.from({ length: 5 }, (_, index) => ({
      ...workItem,
      id: `partial-${index + 1}`,
      titulo: `Parcial ${index + 1}`,
    }));
    apiMock.fetchWorkQueuePage.mockResolvedValue({
      items: firstItems,
      page: 1,
      pageSize: 25,
      total: 8,
    });
    apiMock.fetchRemainingWorkQueuePages.mockRejectedValue(
      new Error("página 2 offline"),
    );

    await renderScreen();

    expect(container.querySelectorAll(".dh-item")).toHaveLength(3);
    expect(container.textContent).toContain("5 de 8 ações estão disponíveis");
    expect(container.textContent).toContain("Parcial 1");
    expect(buttonWithText("Ver 5 ações já carregadas")).toBeDefined();
    expect(buttonWithText("Ver todas as 8 ações")).toBeUndefined();
    expect(container.textContent).not.toContain("Fila zerada.");
  });

  it("oculta imediatamente dados amplos após rebaixamento para membro", async () => {
    const remainder = deferred<{ items: WorkItem[]; total: number }>();
    apiMock.fetchWorkQueuePage.mockResolvedValue({
      items: [workItem],
      page: 1,
      pageSize: 25,
      total: 2,
    });
    apiMock.fetchRemainingWorkQueuePages.mockReturnValue(remainder.promise);

    await renderScreen();
    expect(container.textContent).toContain(workItem.titulo);

    authState.roles = ["membro"];
    await renderScreen();

    remainder.resolve({
      items: [{ ...workItem, id: "stale", titulo: "Ação obsoleta" }],
      total: 2,
    });
    await flush();

    expect(container.textContent).not.toContain(workItem.titulo);
    expect(container.textContent).not.toContain("Ação obsoleta");
    expect(container.textContent).toContain("Para você");
    expect(apiMock.fetchWorkQueuePage).toHaveBeenCalledTimes(1);
  });

  it("mantém a fila quando somente a visão geral falha", async () => {
    authState.roles = ["lider_celula"];
    apiMock.fetchOverview.mockRejectedValueOnce(new Error("overview offline"));

    await renderScreen();

    expect(container.textContent).toContain(workItem.titulo);
    expect(container.textContent).toContain(
      "A fila está atualizada. Dados complementares indisponíveis agora: visão geral.",
    );
  });

  it("preserva a fila e remove somente atribuição quando o lookup falha", async () => {
    apiMock.fetchTeamLookup.mockRejectedValueOnce(new Error("equipe offline"));

    await renderScreen();

    expect(container.textContent).toContain(workItem.titulo);
    expect(buttonWithText("Assumir")).toBeDefined();
    expect(buttonWithText("Atribuir")).toBeUndefined();
    expect(container.textContent).toContain("indisponíveis agora: equipe");
  });

  it("preserva a fila e remove somente vínculo quando a lista de células falha", async () => {
    apiMock.fetchCells.mockRejectedValueOnce(new Error("células offline"));

    await renderScreen();

    expect(container.textContent).toContain(workItem.titulo);
    expect(buttonWithText("Assumir")).toBeDefined();
    expect(buttonWithText("Conectar à célula")).toBeUndefined();
    expect(container.textContent).toContain("indisponíveis agora: células");
  });

  it("explica falha inicial da fila sem mostrar um vazio falso", async () => {
    apiMock.fetchWorkQueuePage.mockRejectedValueOnce(new Error("offline"));

    await renderScreen();

    expect(container.textContent).toContain("Não foi possível carregar a fila de trabalho.");
    expect(container.textContent).toContain("A fila não pôde ser carregada.");
    expect(container.textContent).not.toContain("Fila zerada.");
  });

  it("preserva o evento quando outro bloco contextual falha", async () => {
    authState.roles = ["membro"];
    apiMock.fetchEvents.mockResolvedValue({
      items: [
        {
          id: "e2",
          titulo: "Culto de ensino",
          data: "2999-08-14",
          hora: "20:00",
          descricao: null,
          googleEventId: null,
          sincronizado: false,
          status: "confirmado",
        },
      ],
      page: 1,
      pageSize: 200,
      total: 1,
    });
    apiMock.getNextMeeting.mockRejectedValueOnce(new Error("célula offline"));

    await renderScreen();

    expect(container.textContent).toContain("Culto de ensino");
    expect(container.textContent).toContain("Reunião indisponível agora");
    expect(container.textContent).not.toContain("Nenhuma próxima reunião planejada");
    expect(container.textContent).toContain(
      "Algumas informações de hoje não puderam ser atualizadas.",
    );
  });

  it("não mostra vazio falso de avisos quando falha o escopo das células lideradas", async () => {
    authState.roles = ["lider_celula"];
    apiMock.getLedCellsTodayContext.mockRejectedValueOnce(
      new Error("contexto da liderança offline"),
    );
    apiMock.listNotices.mockResolvedValue({
      items: [
        {
          id: "notice-cell",
          origem: "manual",
          escopo: "celula",
          titulo: "Aviso da célula",
          conteudo: "Cuidado local",
          publicado_em: "2026-08-11T12:00:00Z",
          celula_id: "c1",
        },
      ],
      page: 1,
      page_size: 50,
      total: 1,
    });

    await renderScreen();

    expect(container.textContent).toContain("Avisos indisponíveis agora");
    expect(container.textContent).not.toContain("Nenhum aviso novo");
    expect(container.textContent).not.toContain("Aviso da célula");
  });

  it("distingue indisponibilidade total do contexto", async () => {
    authState.roles = ["membro"];
    apiMock.fetchEvents.mockRejectedValueOnce(new Error("agenda offline"));
    apiMock.getNextMeeting.mockRejectedValueOnce(new Error("célula offline"));
    apiMock.getMyNotices.mockRejectedValueOnce(new Error("avisos offline"));

    await renderScreen();

    expect(container.textContent).toContain(
      "Não foi possível carregar agenda, reunião e avisos.",
    );
    expect(container.textContent).toContain("Agenda indisponível agora");
    expect(container.textContent).toContain("Reunião indisponível agora");
    expect(container.textContent).toContain("Avisos indisponíveis agora");
    expect(container.textContent).not.toContain("Nenhum evento futuro publicado");
    expect(container.textContent).not.toContain("Nenhuma próxima reunião planejada");
    expect(container.textContent).not.toContain("Nenhum aviso novo");
  });
});
