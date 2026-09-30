// @vitest-environment jsdom
import { act, createElement as h, StrictMode, type ComponentProps, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Conversation } from "@/lib/conversations-api";
import { ConversationThread } from "./ConversationThread";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const conversation = (id: string): Conversation => ({
  id, telefone: "telefone-sintetico", pessoaId: null, nome: "Contato sintético",
  estado: "humano", ultimaMensagem: null, naoLidas: 0,
  assumidoPor: "operador-sintetico", assumidoPorNome: null, assumidoEm: null,
  esperaDesde: null, atualizadoEm: null, tipo: null, semInteresse: false,
});
const A = conversation("conversa-a");
const B = conversation("conversa-b");
const contextA = {};
const contextB = {};
type TestThreadProps = Omit<
  ComponentProps<typeof ConversationThread>,
  "draft" | "onDraftChange" | "sendingText"
> & Partial<Pick<ComponentProps<typeof ConversationThread>, "draft" | "onDraftChange" | "sendingText">>;

function ControlledThread({
  draft: initialDraft,
  onDraftChange: parentOnDraftChange,
  sendingText = false,
  ...props
}: TestThreadProps) {
  const [draft, setDraft] = useState(initialDraft ?? "");
  return h(ConversationThread, {
    ...props,
    draft,
    onDraftChange: (value: string) => {
      setDraft(value);
      parentOnDraftChange?.(value);
    },
    sendingText,
  });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
function stream() {
  const tracks = [{ stop: vi.fn() }, { stop: vi.fn() }];
  return { value: { getTracks: () => tracks } as unknown as MediaStream, tracks };
}
class Recorder {
  static instances: Recorder[] = [];
  static fail: "constructor" | "start" | null = null;
  static isTypeSupported = () => true;
  state = "inactive";
  mimeType = "audio/webm";
  ondataavailable: ((event: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;
  start = vi.fn(() => {
    if (Recorder.fail === "start") throw new Error("falha sintética");
    this.state = "recording";
  });
  // Browser events deliberately queued until the test delivers them.
  stop = vi.fn(() => { this.state = "inactive"; });
  constructor(readonly stream: MediaStream) {
    if (Recorder.fail === "constructor") throw new Error("falha sintética");
    Recorder.instances.push(this);
  }
  data(value = "audio-sintetico") { this.ondataavailable?.({ data: new Blob([value]) }); }
  stopped() { this.onstop?.(); }
}
let container: HTMLDivElement;
let root: Root;
let mounted: boolean;
let getUserMedia: ReturnType<typeof vi.fn>;
let onSendMedia: ReturnType<typeof vi.fn<(c: Conversation, file: File, caption?: string) => Promise<boolean>>>;
let requests: ReturnType<typeof deferred<MediaStream>>[];

function render(c = A, context = contextA, overrides: Partial<ComponentProps<typeof ConversationThread>> = {}) {
  const props: TestThreadProps = {
    conversation: c, selfId: "operador-sintetico", recordingContext: context,
    holderName: null, degraded: false, agentAvailability: "active", busy: false,
    conflict: null, messages: [], messagesLoading: false, panelOpen: false,
    isAdmin: false, avatarUrl: null, onAssume: vi.fn(), onReturn: vi.fn(),
    onSend: async () => true, onSendMedia, onTogglePanel: vi.fn(), onDelete: vi.fn(),
    onTransfer: vi.fn(), ...overrides,
  };
  act(() => root.render(h(ControlledThread, props)));
}
function button(label: string) {
  const result = [...container.querySelectorAll<HTMLButtonElement>("button")].find(
    (b) => b.getAttribute("aria-label") === label || b.textContent?.trim() === label,
  );
  expect(result, label).toBeDefined();
  return result!;
}
function click(label: string) { act(() => button(label).click()); }
function enterDraft(value: string) {
  const input = container.querySelector<HTMLInputElement>('input[type="text"]')!;
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  return input;
}
function noAttachment() { expect(container.querySelector(".attach-chip")).toBeNull(); }
function stopped(s: ReturnType<typeof stream>) {
  for (const track of s.tracks) expect(track.stop).toHaveBeenCalled();
}
async function grant(index: number, s: ReturnType<typeof stream>) {
  await act(async () => requests[index]!.resolve(s.value));
}
async function readyAudio() {
  click("Gravar áudio");
  const current = stream(); await grant(requests.length - 1, current);
  const rec = Recorder.instances.at(-1)!;
  act(() => rec.data());
  click("Pronto");
  act(() => rec.stopped());
  return current;
}
beforeEach(() => {
  vi.useFakeTimers();
  Recorder.instances = [];
  Recorder.fail = null;
  requests = [];
  getUserMedia = vi.fn(() => {
    const request = deferred<MediaStream>();
    requests.push(request);
    return request.promise;
  });
  onSendMedia = vi.fn(async () => true);
  vi.stubGlobal("MediaRecorder", Recorder);
  vi.stubGlobal("navigator", { mediaDevices: { getUserMedia } });
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  mounted = true;
});
afterEach(() => {
  if (mounted) act(() => root.unmount());
  container.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("AUD02 microphone ownership", () => {
  it.each([false, true])("discards late A permission after A->B, return to A=%s", async (returnToA) => {
    render(); click("Gravar áudio"); render(B);
    if (returnToA) render(A);
    const old = stream(); await grant(0, old);
    stopped(old);
    expect(Recorder.instances).toHaveLength(0);
    expect(vi.getTimerCount()).toBe(0);
    noAttachment();
    expect(onSendMedia).not.toHaveBeenCalled();
  });
  it("closes every late track after unmount", async () => {
    render(); click("Gravar áudio");
    act(() => root.unmount()); mounted = false;
    const old = stream(); await grant(0, old);
    stopped(old);
    expect(Recorder.instances).toHaveLength(0);
    expect(vi.getTimerCount()).toBe(0);
  });
  it("invalidates equal conversation IDs when the authorized context changes", async () => {
    render(); click("Gravar áudio"); render(A, contextB);
    const old = stream(); await grant(0, old);
    stopped(old);
    expect(Recorder.instances).toHaveLength(0);
    noAttachment();
  });
  it.each([{ degraded: true }, { conversation: { ...A, assumidoPor: "outro-operador" } }])(
    "discards permission after canCompose is lost: %j", async (override) => {
      render(); click("Gravar áudio"); render(A, contextA, override);
      const old = stream(); await grant(0, old);
      stopped(old);
      expect(Recorder.instances).toHaveLength(0);
      noAttachment();
    },
  );
  it("stops active audio on lost authorization and ignores queued events even after recovery", async () => {
    render(); click("Gravar áudio");
    const old = stream(); await grant(0, old);
    const rec = Recorder.instances[0]!;
    render(A, contextA, { degraded: true }); render();
    stopped(old);
    expect(rec.stop).toHaveBeenCalled();
    act(() => { rec.data(); rec.stopped(); });
    noAttachment();
    expect(vi.getTimerCount()).toBe(0);
  });
  it("allows only one permission request for simultaneous clicks", async () => {
    render();
    const mic = button("Gravar áudio");
    act(() => { mic.click(); mic.click(); });
    expect(getUserMedia).toHaveBeenCalledTimes(1);
    const current = stream(); await grant(0, current);
    expect(Recorder.instances).toHaveLength(1);
    expect(vi.getTimerCount()).toBe(1);
  });
  it.each([false, true])("old callbacks cannot affect new recording, return to A=%s", async (returnToA) => {
    render(); click("Gravar áudio");
    const old = stream(); await grant(0, old);
    const oldRec = Recorder.instances[0]!;
    act(() => oldRec.data("antigo"));
    render(B);
    if (returnToA) render(A);
    click("Gravar áudio");
    const current = stream(); await grant(1, current);
    const currentRec = Recorder.instances[1]!;
    act(() => { oldRec.data("antigo"); oldRec.stopped(); oldRec.stopped(); });
    noAttachment();
    for (const track of current.tracks) expect(track.stop).not.toHaveBeenCalled();
    expect(currentRec.stop).not.toHaveBeenCalled();
    expect(container.textContent).toContain("Gravando áudio");
    expect(vi.getTimerCount()).toBe(1);
    act(() => vi.advanceTimersByTime(1000));
    expect(container.querySelector(".rec-time")?.textContent).toBe("0:01");
    act(() => currentRec.data("novo"));
    click("Pronto"); act(() => currentRec.stopped());
    await act(async () => button("Enviar mensagem").click());
    expect(onSendMedia.mock.calls[0]![0]).toBe(returnToA ? A : B);
    expect(onSendMedia.mock.calls[0]![1].size).toBe(new Blob(["novo"]).size);
  });
  it("cancel immediately discards callbacks and permits a new recording in A", async () => {
    render(); click("Gravar áudio");
    const old = stream(); await grant(0, old);
    const oldRec = Recorder.instances[0]!;
    click("Cancelar"); stopped(old); noAttachment();
    click("Gravar áudio");
    const current = stream(); await grant(1, current);
    act(() => { oldRec.data(); oldRec.stopped(); });
    noAttachment();
    for (const track of current.tracks) expect(track.stop).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(1);
  });
  it("late old permission stops only old tracks while B records", async () => {
    render(); click("Gravar áudio"); render(B); click("Gravar áudio");
    const current = stream(); await grant(1, current);
    const old = stream(); await grant(0, old);
    stopped(old);
    for (const track of current.tracks) expect(track.stop).not.toHaveBeenCalled();
    expect(Recorder.instances).toHaveLength(1);
    expect(Recorder.instances[0]!.stop).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(1);
    noAttachment();
  });
  it("old rejection cannot stop a newer recording", async () => {
    render(); click("Gravar áudio"); render(B); click("Gravar áudio");
    const current = stream(); await grant(1, current);
    await act(async () => requests[0]!.reject(new Error("recusa sintética")));
    for (const track of current.tracks) expect(track.stop).not.toHaveBeenCalled();
    expect(container.textContent).toContain("Gravando áudio");
    expect(vi.getTimerCount()).toBe(1);
  });
  it("refused permission creates no attachment or timer", async () => {
    render(); click("Gravar áudio");
    await act(async () => requests[0]!.reject(new Error("recusa sintética")));
    expect(Recorder.instances).toHaveLength(0);
    expect(vi.getTimerCount()).toBe(0);
    noAttachment();
  });
  it.each(["context", "ownership", "degraded"])("ready audio is invalidated by %s", async (change) => {
    render(); await readyAudio();
    expect(container.querySelector(".attach-chip")).not.toBeNull();
    if (change === "context") render(A, contextB);
    if (change === "ownership") render(A, contextA, { conversation: { ...A, assumidoPor: null } });
    if (change === "degraded") render(A, contextA, { degraded: true });
    noAttachment();
    expect(button("Enviar mensagem").disabled).toBe(true);
    expect(onSendMedia).not.toHaveBeenCalled();
  });
  it("unmount stops active resources and ignores queued events", async () => {
    render(); click("Gravar áudio");
    const old = stream(); await grant(0, old);
    const rec = Recorder.instances[0]!;
    act(() => root.unmount()); mounted = false;
    stopped(old);
    expect(rec.stop).toHaveBeenCalled();
    act(() => { rec.data(); rec.stopped(); });
    expect(vi.getTimerCount()).toBe(0);
    expect(onSendMedia).not.toHaveBeenCalled();
  });
  it.each(["constructor", "start"] as const)("cleans stream after recorder %s failure", async (failure) => {
    render(); Recorder.fail = failure; click("Gravar áudio");
    const failed = stream(); await grant(0, failed);
    stopped(failed); noAttachment();
    expect(vi.getTimerCount()).toBe(0);
    Recorder.fail = null;
    await readyAudio();
    expect(container.querySelector(".attach-chip")).not.toBeNull();
  });
  it.each(["recorder", "mediaDevices"])("missing %s API leaves no resources and permits recovery", async (api) => {
    render();
    if (api === "recorder") vi.stubGlobal("MediaRecorder", undefined);
    else vi.stubGlobal("navigator", {});
    click("Gravar áudio");
    expect(getUserMedia).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
    noAttachment();
    vi.stubGlobal("MediaRecorder", Recorder);
    vi.stubGlobal("navigator", { mediaDevices: { getUserMedia } });
    await readyAudio();
    expect(container.querySelector(".attach-chip")).not.toBeNull();
  });
  it("StrictMode cleanup discards a pending cycle without stopping the new mount", async () => {
    render();
    act(() => root.render(h(StrictMode, {}, h(ConversationThread, {
      conversation: A, selfId: "operador-sintetico", recordingContext: contextA,
      holderName: null, degraded: false, agentAvailability: "active", busy: false,
      conflict: null, messages: [], messagesLoading: false, panelOpen: false,
      isAdmin: false, avatarUrl: null, onAssume: vi.fn(), onReturn: vi.fn(),
      onSend: async () => true, onSendMedia, onTogglePanel: vi.fn(), onDelete: vi.fn(),
      onTransfer: vi.fn(), draft: "", onDraftChange: vi.fn(), sendingText: false,
    }))));
    click("Gravar áudio");
    render(); click("Gravar áudio");
    const current = stream(); await grant(1, current);
    const old = stream(); await grant(0, old);
    stopped(old);
    for (const track of current.tracks) expect(track.stop).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(1);
  });
  it("empty recording creates no attachment", async () => {
    render(); click("Gravar áudio");
    const current = stream(); await grant(0, current);
    click("Pronto"); act(() => Recorder.instances[0]!.stopped());
    noAttachment(); stopped(current);
    expect(vi.getTimerCount()).toBe(0);
  });
  it.each(["ownership", "degraded", "selfId"])("preserves text draft on temporary %s loss", (change) => {
    render();
    const input = enterDraft("rascunho sintético");
    expect(input.value).toBe("rascunho sintético");
    if (change === "ownership") render(A, contextA, { conversation: { ...A, assumidoPor: null } });
    if (change === "degraded") render(A, contextA, { degraded: true });
    if (change === "selfId") render(A, contextA, { selfId: "outro-operador" });
    expect(input.value).toBe("rascunho sintético");
    render();
    expect(input.value).toBe("rascunho sintético");
  });
  it("normal A recording creates audio and sends exactly to A", async () => {
    render();
    const current = await readyAudio();
    stopped(current);
    expect(vi.getTimerCount()).toBe(0);
    expect(container.querySelector(".attach-name")?.textContent).toBe("mensagem-de-voz.webm");
    enterDraft("legenda sintética");
    await act(async () => button("Enviar mensagem").click());
    expect(onSendMedia).toHaveBeenCalledTimes(1);
    const [target, file, caption] = onSendMedia.mock.calls[0]!;
    expect(caption).toBe("legenda sintética");
    expect(target).toBe(A);
    expect(file).toBeInstanceOf(File);
    expect(file.type).toBe("audio/webm");
    expect(file.size).toBe(new Blob(["audio-sintetico"]).size);
    noAttachment();
  });
});
