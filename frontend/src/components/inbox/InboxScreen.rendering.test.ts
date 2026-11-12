// @vitest-environment jsdom
import { act, createElement as h } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import type { Conversation } from "@/lib/conversations-api";

const auth = vi.hoisted(() => ({
  token: "synthetic-rendering-token",
  status: "authenticated",
  user: { roles: ["pastor"], appUserId: "synthetic-user", churchId: "synthetic-church" },
  expireSession: vi.fn(),
}));
const api = vi.hoisted(() => ({
  fetchConversations: vi.fn(),
  fetchInboxAgentStatus: vi.fn(),
  fetchMessageWindow: vi.fn(),
  fetchConversationPhoto: vi.fn(),
  markConversationRead: vi.fn(),
}));
vi.mock("@/lib/auth-context", () => ({ useAuth: () => auth }));
vi.mock("@/lib/conversations-api", async (importOriginal) => ({
  ...(await importOriginal()),
  ...api,
}));
vi.mock("./conversation-format", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./conversation-format")>();
  return { ...actual, shortTime: vi.fn(actual.shortTime) };
});

const { InboxScreen } = await import("./InboxScreen");
const { shortTime } = await import("./conversation-format");
let root: Root;
let container: HTMLDivElement;
let completePhoto: (url: string | null) => void;

const conversations: Conversation[] = Array.from({ length: 100 }, (_, index) => ({
  id: `synthetic-conversation-${index}`,
  nome: `Contato sintético ${index}`,
  telefone: "SYNTHETIC-CONTACT",
  pessoaId: null,
  estado: "humano",
  ultimaMensagem: "Mensagem sintética",
  naoLidas: 0,
  assumidoPor: "synthetic-user",
  assumidoPorNome: null,
  assumidoEm: null,
  esperaDesde: null,
  atualizadoEm: "2026-10-02T12:00:00Z",
  tipo: null,
  semInteresse: false,
}));

beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-10-02T12:00:00Z"));
  for (const mock of Object.values(api)) mock.mockReset();
  vi.mocked(shortTime).mockClear();
  api.fetchConversations.mockResolvedValue({
    items: conversations,
    total: 100,
    page: 1,
    pageSize: 100,
  });
  api.fetchInboxAgentStatus.mockResolvedValue({
    configured: true,
    ativo: true,
    pausedByChurch: false,
  });
  api.fetchMessageWindow.mockResolvedValue({
    items: [],
    total: 0,
    page: 1,
    pageSize: 50,
    cursorSupported: true,
    nextBefore: null,
    nextAfter: null,
  });
  api.fetchConversationPhoto.mockImplementation(
    () =>
      new Promise<string | null>((resolve) => {
        completePhoto = resolve;
      }),
  );
  api.markConversationRead.mockResolvedValue(undefined);
  vi.stubGlobal(
    "fetch",
    vi.fn(() => {
      throw new Error("Network forbidden");
    }),
  );
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener() {},
    removeEventListener() {},
  }));
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "visible" });
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  Reflect.deleteProperty(document, "visibilityState");
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

it("typing a draft keeps the unchanged 100-row list out of rendering", async () => {
  await act(async () => {
    root.render(h(InboxScreen));
  });
  expect(container.querySelectorAll("button.conv")).toHaveLength(100);
  const composer = container.querySelector<HTMLInputElement>('[aria-label="Resposta ao contato"]')!;
  expect(composer.disabled).toBe(false);
  vi.mocked(shortTime).mockClear();
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(
      composer,
      "Rascunho sintético",
    );
    composer.dispatchEvent(new Event("input", { bubbles: true }));
  });
  expect(composer.value).toBe("Rascunho sintético");
  expect(vi.mocked(shortTime).mock.calls.length).toBe(0);
});

it("receiving the selected contact photo does not render the unchanged list", async () => {
  await act(async () => {
    root.render(h(InboxScreen));
  });
  expect(container.querySelectorAll("button.conv")).toHaveLength(100);
  vi.mocked(shortTime).mockClear();
  await act(async () => {
    completePhoto("https://example.test/synthetic-photo");
  });
  expect(container.querySelector('img[src="https://example.test/synthetic-photo"]')).not.toBeNull();
  expect(vi.mocked(shortTime).mock.calls.length).toBe(0);
});

it("selection, search and filters continue updating the list", async () => {
  await act(async () => {
    root.render(h(InboxScreen));
  });
  const second = container.querySelectorAll<HTMLButtonElement>("button.conv")[1]!;
  await act(async () => {
    second.click();
  });
  expect(second.getAttribute("aria-current")).toBe("true");
  expect(container.querySelectorAll('.conv[aria-current="true"]')).toHaveLength(1);
  const search = container.querySelector<HTMLInputElement>('[aria-label="Buscar conversa"]')!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(
      search,
      "Contato sintético 99",
    );
    search.dispatchEvent(new Event("input", { bubbles: true }));
  });
  expect(container.querySelectorAll("button.conv")).toHaveLength(1);
  expect(container.querySelector("button.conv")?.textContent).toContain("Contato sintético 99");
  const waiting = [...container.querySelectorAll<HTMLButtonElement>(".ib-filter-btn")].find(
    (button) => button.textContent?.includes("Em espera"),
  )!;
  await act(async () => {
    waiting.click();
  });
  expect(waiting.getAttribute("aria-pressed")).toBe("true");
  expect(container.querySelectorAll("button.conv")).toHaveLength(0);
});

it("the load-more action still requests the next page and announces completion", async () => {
  api.fetchConversations.mockImplementation(async (_token, _size, _signal, page) => ({
    items:
      page === 1
        ? conversations
        : [{ ...conversations[0], id: "synthetic-final", nome: "Contato sintético final" }],
    total: 101,
    page,
    pageSize: 100,
  }));
  await act(async () => {
    root.render(h(InboxScreen));
  });
  const more = [...container.querySelectorAll<HTMLButtonElement>("button")].find((button) =>
    button.textContent?.includes("Carregar mais conversas"),
  )!;
  more.focus();
  await act(async () => {
    more.click();
  });
  expect(api.fetchConversations.mock.calls.map((call) => call[3])).toEqual([1, 1, 2]);
  expect(container.querySelectorAll("button.conv")).toHaveLength(101);
  expect(container.querySelector(".conv-list [role='status']")?.textContent).toContain(
    "Todas as 101 conversas foram carregadas.",
  );
  expect(document.activeElement).toBe(container.querySelector('[aria-label="Buscar conversa"]'));
});

it("polling renders immutable updated rows and keeps selection callbacks current", async () => {
  await act(async () => {
    root.render(h(InboxScreen));
  });
  const updated = conversations.map((conversation, index) =>
    index === 1
      ? { ...conversation, nome: "Contato sintético atualizado", estado: "aguardando" as const }
      : conversation,
  );
  api.fetchConversations.mockResolvedValue({ items: updated, total: 100, page: 1, pageSize: 100 });
  vi.mocked(shortTime).mockClear();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(15_000);
  });
  expect(vi.mocked(shortTime).mock.calls.length).toBeGreaterThanOrEqual(100);
  const changed = [...container.querySelectorAll<HTMLButtonElement>("button.conv")].find((button) =>
    button.textContent?.includes("Contato sintético atualizado"),
  )!;
  expect(changed.textContent).toContain("Em espera");
  expect(conversations[1]?.nome).toBe("Contato sintético 1");
  await act(async () => {
    changed.click();
  });
  expect(changed.getAttribute("aria-current")).toBe("true");
  expect(api.fetchMessageWindow.mock.calls.at(-1)?.[1]).toBe("synthetic-conversation-1");
});
