import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Role } from "./roles";

const apiMock = vi.hoisted(() => ({
  fetchPipeline: vi.fn(),
  fetchConversations: vi.fn(),
  fetchCells: vi.fn(),
  fetchOverview: vi.fn(),
  fetchTeamLookup: vi.fn(),
  fetchWorkQueuePage: vi.fn(),
  fetchEvents: vi.fn(),
  fetchUpcomingEvents: vi.fn(),
}));

vi.mock("./contacts-api", () => ({
  fetchPipeline: apiMock.fetchPipeline,
}));

vi.mock("./conversations-api", () => ({
  fetchConversations: apiMock.fetchConversations,
}));

vi.mock("./dashboard-api", () => ({
  fetchCells: apiMock.fetchCells,
  fetchOverview: apiMock.fetchOverview,
  fetchTeamLookup: apiMock.fetchTeamLookup,
  fetchWorkQueuePage: apiMock.fetchWorkQueuePage,
}));

vi.mock("./events-api", () => ({
  fetchEvents: apiMock.fetchEvents,
  fetchUpcomingEvents: apiMock.fetchUpcomingEvents,
}));

const { preloadRouteData } = await import("./route-data-preload");

beforeEach(() => {
  for (const mock of Object.values(apiMock)) {
    mock.mockReset();
    mock.mockResolvedValue(undefined);
  }
});

describe("preloadRouteData — capacidades do dashboard", () => {
  const roleCases: Array<
    [
      role: Role,
      canLinkCell: boolean,
      canAssignQueue: boolean,
      hasWorkQueue: boolean,
      canSeeCalendar: boolean,
    ]
  > = [
    ["admin", true, true, true, true],
    ["pastor", true, true, true, true],
    ["lider_g12", false, true, true, true],
    ["lider_consol", false, true, true, true],
    ["lider_celula", false, false, true, true],
    ["lider_mult", false, false, false, true],
    ["operador", false, false, false, false],
    ["membro", false, false, false, true],
  ];

  it.each(roleCases)(
    "pré-carrega células conforme o papel %s",
    async (role, canLinkCell, canAssignQueue, hasWorkQueue, canSeeCalendar) => {
      await preloadRouteData("tok-1", "dashboard", [role]);
      await preloadRouteData("tok-1", "ganhar", [role]);

      expect(apiMock.fetchWorkQueuePage).toHaveBeenCalledTimes(hasWorkQueue ? 1 : 0);
      if (hasWorkQueue) {
        expect(apiMock.fetchWorkQueuePage).toHaveBeenCalledWith("tok-1", 1, 25);
      }
      expect(apiMock.fetchTeamLookup).toHaveBeenCalledTimes(canAssignQueue ? 1 : 0);
      expect(apiMock.fetchOverview).toHaveBeenCalledTimes(hasWorkQueue ? 1 : 0);
      expect(apiMock.fetchUpcomingEvents).toHaveBeenCalledTimes(
        canSeeCalendar ? 1 : 0,
      );
      expect(apiMock.fetchPipeline).toHaveBeenCalledWith("tok-1", "ganhar");
      expect(apiMock.fetchCells).toHaveBeenCalledTimes(canLinkCell ? 2 : 0);
    },
  );

  it("respeita papéis acumulados quando pastor não é o papel primário", async () => {
    const roles: Role[] = ["membro", "lider_celula", "pastor"];

    await preloadRouteData("tok-1", "dashboard", roles);
    await preloadRouteData("tok-1", "ganhar", roles);

    expect(apiMock.fetchCells).toHaveBeenCalledTimes(2);
  });

  it("preserva os preloads de calendário e inbox", async () => {
    await preloadRouteData("tok-1", "calendario", ["membro"]);
    await preloadRouteData("tok-1", "inbox", ["membro"]);

    expect(apiMock.fetchEvents).toHaveBeenCalledWith("tok-1");
    expect(apiMock.fetchConversations).toHaveBeenCalledWith("tok-1");
    expect(apiMock.fetchCells).not.toHaveBeenCalled();
  });

  it("usa a mesma matriz efetiva da sessão ao decidir o preload opcional", async () => {
    await preloadRouteData(
      "tok-1",
      "dashboard",
      ["membro"],
      { membro: ["dashboard"] },
    );

    expect(apiMock.fetchUpcomingEvents).not.toHaveBeenCalled();
  });

  it("mantém falhas de prefetch silenciosas com allSettled", async () => {
    apiMock.fetchWorkQueuePage.mockRejectedValueOnce(new Error("offline"));

    await expect(
      preloadRouteData("tok-1", "dashboard", ["lider_celula"]),
    ).resolves.toBeUndefined();
    expect(apiMock.fetchOverview).toHaveBeenCalledOnce();
  });
});
