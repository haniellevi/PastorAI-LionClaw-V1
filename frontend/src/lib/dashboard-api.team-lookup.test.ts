import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchTeamLookup } from "./dashboard-api";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchTeamLookup — paginação completa do seletor", () => {
  it("busca todas as páginas para não esconder um destino elegível após o limite", async () => {
    const firstPage = Array.from({ length: 200 }, (_, index) => ({
      usuarioId: `u-${index}`,
      nome: `Pessoa ${index}`,
      email: "",
      status: "ativo",
      papeis: ["lider_celula"],
      pessoaId: null,
      tiposFila: ["relatorio"],
    }));
    const eligible = {
      usuarioId: "u-eligible",
      nome: "Destino elegível",
      email: "",
      status: "ativo",
      papeis: ["lider_consol"],
      pessoaId: null,
      tiposFila: ["visitante"],
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({ items: firstPage, page: 1, pageSize: 200, total: 201 }),
          { status: 200 },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({ items: [eligible], page: 2, pageSize: 200, total: 201 }),
          { status: 200 },
        ),
      );
    vi.stubGlobal("fetch", fetchMock);

    const result = await fetchTeamLookup("tok-1");

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(String(fetchMock.mock.calls[0]?.[0])).toContain("page=1&pageSize=200");
    expect(String(fetchMock.mock.calls[1]?.[0])).toContain("page=2&pageSize=200");
    expect(result.total).toBe(201);
    expect(result.items).toHaveLength(201);
    expect(result.items.at(-1)).toEqual(eligible);
  });
});
