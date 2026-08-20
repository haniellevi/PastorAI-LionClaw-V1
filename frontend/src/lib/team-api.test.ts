import { afterEach, describe, expect, it, vi } from "vitest";

import { inviteMember } from "./team-api";

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
