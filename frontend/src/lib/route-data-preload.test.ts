import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Role } from "./roles";

const apiMock = vi.hoisted(() => ({
  fetchPipeline: vi.fn(),
  fetchConversations: vi.fn(),
  fetchCells: vi.fn(),
  fetchOverview: vi.fn(),
  fetchTeamLookup: vi.fn(),
  fetchWorkQueue: vi.fn(),
  fetchEvents: vi.fn(),
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
  fetchWorkQueue: apiMock.fetchWorkQueue,
}));

vi.mock("./events-api", () => ({
  fetchEvents: apiMock.fetchEvents,
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
    [role: Role, canLinkCell: boolean, canAssignQueue: boolean]
  > = [
    ["admin", true, true],
    ["pastor", true, true],
    ["lider_g12", false, true],
    ["lider_consol", false, true],
    ["lider_celula", false, false],
    ["lider_mult", false, false],
    ["operador", false, false],
    ["membro", false, false],
  ];

  it.each(roleCases)(
    "pré-carrega células conforme o papel %s",
    async (role, canLinkCell, canAssignQueue) => {
      await preloadRouteData("tok-1", "dashboard", [role]);
      await preloadRouteData("tok-1", "ganhar", [role]);

      expect(apiMock.fetchWorkQueue).toHaveBeenCalledOnce();
      expect(apiMock.fetchTeamLookup).toHaveBeenCalledTimes(canAssignQueue ? 1 : 0);
      expect(apiMock.fetchOverview).toHaveBeenCalledOnce();
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

  it("mantém falhas de prefetch silenciosas com allSettled", async () => {
    apiMock.fetchWorkQueue.mockRejectedValueOnce(new Error("offline"));

    await expect(
      preloadRouteData("tok-1", "dashboard", ["lider_celula"]),
    ).resolves.toBeUndefined();
    expect(apiMock.fetchOverview).toHaveBeenCalledOnce();
  });
});
