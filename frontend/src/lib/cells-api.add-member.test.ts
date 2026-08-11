import { afterEach, describe, expect, it, vi } from "vitest";

import { addCellMember } from "./cells-api";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("addCellMember", () => {
  it("usa o endpoint de vínculo e nunca o endpoint de convite da Equipe", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ id: "cm-1", pessoaId: "p-1", papel: "membro", ativo: true }),
        { status: 200 },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await addCellMember("tok-1", "cell-1", "p-1");

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/cells/cell-1/membros");
    expect(url).not.toContain("/team/invite");
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({ pessoaId: "p-1" });
    expect(result.pessoaId).toBe("p-1");
  });
});
