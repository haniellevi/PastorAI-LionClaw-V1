import { afterEach, describe, expect, it, vi } from "vitest";

import { inviteMember, linkPessoa } from "./team-api";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("inviteMember", () => {
  it("concede acesso a uma Pessoa vinculada sem enviar celulaId", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ usuarioId: "u-1", status: "convidado", emailEnviado: true }),
        { status: 200 },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await inviteMember("tok-1", {
      pessoaId: "p-vinculada",
      email: "ana@example.com",
    });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/team/invite");
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({
      pessoaId: "p-vinculada",
      email: "ana@example.com",
    });
    expect(String(init.body)).not.toContain("celulaId");
  });
});


it.each(["p-synthetic", null])("envia vínculo explícito %s", async (pessoaId) => {
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ usuarioId: "u", pessoaId }), { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
  expect(await linkPessoa("tok", "u", pessoaId)).toEqual({ usuarioId: "u", pessoaId });
  const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
  expect(url).toContain("/team/u/pessoa");
  expect(init.method).toBe("PUT");
  expect(JSON.parse(String(init.body))).toEqual({ pessoaId });
});
it("preserva recusa 409 do servidor", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "Pessoa já vinculada" }), { status: 409 })));
  await expect(linkPessoa("tok", "u", "p")).rejects.toThrow("Pessoa já vinculada");
});
