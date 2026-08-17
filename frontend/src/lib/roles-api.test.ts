import { beforeEach, describe, expect, it, vi } from "vitest";

const apiMock = vi.hoisted(() => ({
  authedFetch: vi.fn(),
}));

vi.mock("./dashboard-api", () => ({
  ApiError: class ApiError extends Error {
    constructor(
      readonly status: number,
      message: string,
    ) {
      super(message);
    }
  },
  authedFetch: apiMock.authedFetch,
  readDetail: vi.fn(),
}));

const { fetchPermissions, savePermissions } = await import("./roles-api");

beforeEach(() => {
  apiMock.authedFetch.mockReset();
});

describe("roles-api — matriz completa", () => {
  it("preserva a linha de operador recebida do backend", async () => {
    apiMock.authedFetch.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          matriz: {
            operador: ["dashboard", "inbox"],
            membro: ["dashboard"],
          },
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    const matrix = await fetchPermissions("token-a");

    expect(matrix.operador).toEqual(["dashboard", "inbox"]);
  });

  it("envia a linha de operador ao salvar a matriz", async () => {
    apiMock.authedFetch.mockResolvedValueOnce(
      new Response(JSON.stringify({ matriz: { operador: ["dashboard", "ganhar"] } }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await savePermissions("token-a", {
      operador: ["dashboard", "ganhar"],
    });

    const init = apiMock.authedFetch.mock.calls[0]?.[2] as RequestInit;
    expect(JSON.parse(String(init.body)).matriz.operador).toEqual([
      "dashboard",
      "ganhar",
    ]);
  });
});
