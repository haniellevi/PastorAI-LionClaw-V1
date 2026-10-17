import { expect, test } from "@playwright/test";
import { API_URL, APP_URL, armBrowserSafety, expectCleanBrowser, loginThroughUi, resetHarness } from "./support/helpers";

const actorId = "00000000-0000-4000-8000-000000000001";
const trackId = "00000000-0000-4000-8000-000000000090";
const invitationId = "00000000-0000-4000-8000-000000000091";

test("destinatário aceita no painel e o responsável efetivo permanece após reload", async ({ page, request }) => {
  await resetHarness(request);
  const safety = await armBrowserSafety(page);
  let accepted = false;
  await page.route(`${API_URL}/consolidacao/**`, async route => {
    const path = new URL(route.request().url()).pathname;
    const headers = { "Access-Control-Allow-Origin": APP_URL, "Access-Control-Allow-Headers": "Authorization, Content-Type", "Access-Control-Allow-Methods": "GET, POST, OPTIONS" };
    if (route.request().method() === "OPTIONS") { await route.fulfill({ status: 204, headers }); return; }
    const invitation = { id: invitationId, consolidacaoId: trackId, responsavelId: actorId, status: accepted ? "aceita" : "atribuida", prazoAceite: "2099-10-18T18:00:00Z", autoatribuicao: false };
    if (path.endsWith("/resposta")) {
      expect(route.request().postDataJSON()).toEqual({ aceitar: true });
      accepted = true;
      await route.fulfill({ headers, json: { ...invitation, status: "aceita" } });
    } else {
      await route.fulfill({ headers, json: { items: [{ id: trackId, pessoaId: "synthetic-person", pessoaNome: "Pessoa fictícia do aceite", responsavelId: accepted ? actorId : null, prazoConexao: null, etapasConfirmadas: [], convite: invitation }], nextCursor: null } });
    }
  });
  await loginThroughUi(page);
  const panel = page.getByRole("region", { name: "Aceite da fonovisita" });
  await expect(panel.getByText("Sem responsável efetivo")).toBeVisible();
  await panel.getByRole("button", { name: "Aceitar fonovisita de Pessoa fictícia do aceite" }).click();
  await expect(panel.getByRole("status")).toContainText("Convite aceito");
  await expect(panel.getByRole("button", { name: /Aceitar fonovisita/ })).toHaveCount(0);
  await page.reload();
  await expect(panel.getByText("Você", { exact: true })).toBeVisible();
  await expect(panel.getByRole("button", { name: /Aceitar fonovisita/ })).toHaveCount(0);
  expectCleanBrowser(safety);
});
