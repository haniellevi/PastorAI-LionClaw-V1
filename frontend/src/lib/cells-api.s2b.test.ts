import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { upsertCell } from "./cells-api";

let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => { fetchMock = vi.fn().mockResolvedValue(Response.json({ id: "cell-1", nome: "Exemplo" })); vi.stubGlobal("fetch", fetchMock); });
afterEach(() => vi.unstubAllGlobals());

const base = { nome: "Exemplo", coberturaEspiritual: "Pastor Exemplo" };

it("cliente antigo não envia novas chaves e preserva valores já gravados", async () => {
  await upsertCell("token-a", base);
  const body = JSON.parse((fetchMock.mock.calls[0]?.[1] as RequestInit).body as string);
  expect(body).not.toHaveProperty("bairro");
  expect(body).not.toHaveProperty("divulgarWhatsapp");
});

it("cliente com capability envia bairro e publicação explicitamente", async () => {
  await upsertCell("token-a", { ...base, bairro: "Centro", divulgarWhatsapp: false });
  const body = JSON.parse((fetchMock.mock.calls[0]?.[1] as RequestInit).body as string);
  expect(body).toMatchObject({ bairro: "Centro", divulgarWhatsapp: false });
});
