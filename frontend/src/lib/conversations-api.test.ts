// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  fetchConversations,
  fetchMessages,
  MAX_MEDIA_BYTES,
  sendMedia,
} from "./conversations-api";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("GETs do inbox", () => {
  it("propaga o AbortSignal para conversas e mensagens", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ items: [], page: 1, pageSize: 100, total: 0 }),
    });
    vi.stubGlobal("fetch", fetchSpy);
    const conversationsController = new AbortController();
    const messagesController = new AbortController();

    await fetchConversations("token", 100, conversationsController.signal);
    await fetchMessages("token", "conversation", 200, messagesController.signal);

    const conversationsCall = fetchSpy.mock.calls.at(0);
    const messagesCall = fetchSpy.mock.calls.at(1);
    if (!conversationsCall || !messagesCall) throw new Error("GETs esperados não foram chamados");
    expect(conversationsCall[1]).toMatchObject({ signal: conversationsController.signal });
    expect(messagesCall[1]).toMatchObject({ signal: messagesController.signal });
  });
});

describe("sendMedia", () => {
  it("rejeita arquivo acima de 16 MB antes de ler ou chamar a rede", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const oversized = { size: MAX_MEDIA_BYTES + 1 } as File;

    await expect(sendMedia("token", "conversation", oversized)).rejects.toThrow(
      "Arquivo excede o limite de 16 MB.",
    );
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
