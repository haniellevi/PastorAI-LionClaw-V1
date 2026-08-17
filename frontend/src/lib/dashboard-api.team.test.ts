import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchTeam, type TeamMember } from "./dashboard-api";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchTeam", () => {
  it("pagina a Equipe completa para não perder candidatos a líder", async () => {
    const first: TeamMember[] = Array.from({ length: 100 }, (_, index) => ({
      usuarioId: `u-${index}`,
      pessoaId: `p-${index}`,
      nome: `Pessoa ${index}`,
      email: `p${index}@example.com`,
      status: "ativo",
      papeis: ["membro"],
    }));
    const last: TeamMember = {
      usuarioId: "u-100",
      pessoaId: "p-100",
      nome: "Última Pessoa",
      email: "ultima@example.com",
      status: null,
      papeis: ["membro"],
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ items: first, page: 1, pageSize: 100, total: 101 }), {
          status: 200,
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ items: [last], page: 2, pageSize: 100, total: 101 }), {
          status: 200,
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    const result = await fetchTeam("tok-1");

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(String(fetchMock.mock.calls[0]?.[0])).toContain("page=1&pageSize=100");
    expect(String(fetchMock.mock.calls[1]?.[0])).toContain("page=2&pageSize=100");
    expect(result.items).toHaveLength(101);
    expect(result.items.at(-1)).toEqual(last);
  });
});
