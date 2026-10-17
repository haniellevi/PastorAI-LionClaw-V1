// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { PrayerRequestsScreen } from "./PrayerRequestsScreen";

const mocks = vi.hoisted(() => ({ token: "synthetic-token", fetch: vi.fn() }));
vi.mock("@/lib/auth-context", () => ({
  useAuth: () => ({ token: mocks.token, user: { appUserId: "pastor-id" } }),
}));
let root: Root;
let container: HTMLDivElement;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  vi.stubGlobal("fetch", mocks.fetch);
  mocks.fetch.mockReset();
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.unstubAllGlobals();
});
const row = {
  id: "request-id",
  summary: "Pedido sintético de paz",
  pessoa_nome: "Contato sintético",
  audience: "pastoral",
  state: "open",
  created_at: "2026-10-16T00:00:00Z",
  responsavel_id: null,
};
it("lists authorized requests and assumes through the authenticated API", async () => {
  mocks.fetch.mockResolvedValueOnce(
    new Response(JSON.stringify([row]), { status: 200 }),
  );
  await act(async () => root.render(<PrayerRequestsScreen />));
  expect(container.textContent).toContain("Pedido sintético de paz");
  expect(container.textContent).toContain("Contato sintético");
  mocks.fetch.mockResolvedValueOnce(
    new Response(
      JSON.stringify({
        ...row,
        state: "assigned",
        responsavel_id: "pastor-id",
      }),
      { status: 200 },
    ),
  );
  await act(async () =>
    Array.from(container.querySelectorAll("button"))
      .find((b) => b.textContent === "Assumir")!
      .click(),
  );
  expect(mocks.fetch.mock.calls[1]![0]).toContain(
    "/prayer-requests/request-id/assume",
  );
  expect(container.textContent).toContain("Em acompanhamento");
});
it("does not display requests when access is refused", async () => {
  mocks.fetch.mockResolvedValueOnce(
    new Response(JSON.stringify({ detail: "Acesso não autorizado" }), {
      status: 403,
    }),
  );
  await act(async () => root.render(<PrayerRequestsScreen />));
  expect(container.textContent).not.toContain("Pedido sintético de paz");
  expect(container.querySelector('[role="alert"]')).not.toBeNull();
});
it("clears previously loaded private text when an action loses authorization", async () => {
  mocks.fetch.mockResolvedValueOnce(
    new Response(JSON.stringify([row]), { status: 200 }),
  );
  await act(async () => root.render(<PrayerRequestsScreen />));
  mocks.fetch.mockResolvedValueOnce(
    new Response(JSON.stringify({ detail: "Acesso não autorizado" }), {
      status: 403,
    }),
  );
  await act(async () =>
    Array.from(container.querySelectorAll("button"))
      .find((b) => b.textContent === "Assumir")!
      .click(),
  );
  expect(container.textContent).not.toContain("Pedido sintético de paz");
  expect(container.querySelector('[role="alert"]')).not.toBeNull();
});
