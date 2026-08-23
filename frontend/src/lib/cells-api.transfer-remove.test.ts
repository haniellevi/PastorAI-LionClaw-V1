// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SessionExpiredError } from "./api";
import { ApiError, authedFetch } from "./dashboard-api";
import { removeCellMember, transferCellMember } from "./cells-api";

vi.mock("./dashboard-api", () => ({
  ApiError: class extends Error {
    constructor(public status: number, message: string) {
      super(message);
    }
  },
  authedFetch: vi.fn(),
  readDetail: vi.fn().mockImplementation(async (res: Response) => {
    const body = await res.json();
    if (typeof body?.detail === "string") return body.detail;
    return null;
  }),
}));

const fetchMock = authedFetch as unknown as ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock.mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("transferCellMember", () => {
  it("envia POST para /cells/{id}/membros/transferir com pessoaId, celula_destino_id e motivo", async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({ id: "m1", pessoaId: "p1", papel: "membro", ativo: true }),
    });
    const result = await transferCellMember(
      "tok",
      "cell-1",
      "p1",
      "cell-2",
      "Mudou de bairro",
    );
    expect(fetchMock).toHaveBeenCalledWith(
      "tok",
      "/cells/cell-1/membros/transferir",
      {
        method: "POST",
        body: JSON.stringify({
          pessoaId: "p1",
          celula_destino_id: "cell-2",
          motivo: "Mudou de bairro",
        }),
      },
    );
    expect(result.pessoaId).toBe("p1");
    expect(result.ativo).toBe(true);
  });

  it("omite motivo quando não fornecido", async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({ id: "m1", pessoaId: "p1", papel: "membro", ativo: true }),
    });
    await transferCellMember("tok", "cell-1", "p1", "cell-2");
    const call = fetchMock.mock.calls[0];
    if (!call) throw new Error("fetch not called");
    const body = JSON.parse(call[2].body);
    expect(body).not.toHaveProperty("motivo");
  });

  it("lança ApiError com detail do backend em falha", async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 409,
      json: async () => ({ detail: "A célula de destino está inativa" }),
    });
    await expect(
      transferCellMember("tok", "cell-1", "p1", "cell-2"),
    ).rejects.toThrow("A célula de destino está inativa");
  });
});

describe("removeCellMember", () => {
  it("envia POST para /cells/{id}/membros/remover com pessoaId e motivo", async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({ id: "m1", pessoaId: "p1", papel: "membro", ativo: false }),
    });
    const result = await removeCellMember("tok", "cell-1", "p1", "Pediu para sair");
    expect(fetchMock).toHaveBeenCalledWith(
      "tok",
      "/cells/cell-1/membros/remover",
      {
        method: "POST",
        body: JSON.stringify({
          pessoaId: "p1",
          motivo: "Pediu para sair",
        }),
      },
    );
    expect(result.ativo).toBe(false);
  });

  it("omite motivo quando não fornecido", async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({ id: "m1", pessoaId: "p1", papel: "membro", ativo: false }),
    });
    await removeCellMember("tok", "cell-1", "p1");
    const call = fetchMock.mock.calls[0];
    if (!call) throw new Error("fetch not called");
    const body = JSON.parse(call[2].body);
    expect(body).not.toHaveProperty("motivo");
  });

  it("lança ApiError com detail do backend em falha", async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 409,
      json: async () => ({ detail: "A pessoa não possui vínculo ativo" }),
    });
    await expect(removeCellMember("tok", "cell-1", "p1")).rejects.toThrow(
      "A pessoa não possui vínculo ativo",
    );
  });
});
