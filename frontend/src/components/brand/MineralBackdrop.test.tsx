// @vitest-environment jsdom
import { act, createElement as h } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { MineralBackdrop } from "./MineralBackdrop";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement;
let root: Root;
let fine: boolean;
let reduced: boolean;
let mediaListeners: Set<() => void>;
let frames: Map<number, FrameRequestCallback>;
let nextFrame: number;

beforeEach(() => {
  fine = true;
  reduced = false;
  mediaListeners = new Set();
  frames = new Map();
  nextFrame = 0;
  vi.stubGlobal("matchMedia", (query: string) => ({
    get matches() { return query.includes("reduced-motion") ? reduced : fine; },
    addEventListener: (_event: string, fn: () => void) => mediaListeners.add(fn),
    removeEventListener: (_event: string, fn: () => void) => mediaListeners.delete(fn),
  }));
  vi.stubGlobal("requestAnimationFrame", (fn: FrameRequestCallback) => { frames.set(++nextFrame, fn); return nextFrame; });
  vi.stubGlobal("cancelAnimationFrame", (id: number) => frames.delete(id));
  host = document.createElement("div");
  host.setAttribute("data-mineral-surface", "");
  host.getBoundingClientRect = () => ({ left: 0, top: 0, width: 400, height: 400 }) as DOMRect;
  document.body.append(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});
function render() { act(() => root.render(h("div", null, h(MineralBackdrop), h("input", { "aria-label": "E-mail" })))); }
function move(x: number, y: number) { host.dispatchEvent(new MouseEvent("pointermove", { clientX: x, clientY: y, bubbles: true })); }
function flushFrame() { const pending = [...frames.values()]; frames.clear(); pending.forEach((fn) => fn(0)); }
function art() { return host.querySelector<HTMLElement>(".mineral-backdrop")!; }

it("limita a decoração a 6px e coalesce vários eventos em um frame", () => {
  render();
  move(900, -100); move(800, -200);
  expect(frames.size).toBe(1);
  flushFrame();
  expect(art().style.getPropertyValue("--mineral-x")).toBe("6px");
  expect(art().style.getPropertyValue("--mineral-y")).toBe("-6px");
  expect(art().getAttribute("aria-hidden")).toBe("true");
});
it("cancela frame e estabiliza a arte ao focar entrada, preservando digitação", () => {
  render(); move(400, 400);
  const input = host.querySelector("input")!;
  input.focus();
  expect(frames.size).toBe(0);
  move(400, 400); flushFrame();
  expect(art().style.getPropertyValue("--mineral-x")).toBe("0px");
  input.value = "rascunho@example.test";
  expect(document.activeElement).toBe(input);
  expect(input.value).toBe("rascunho@example.test");
});
it.each(["coarse", "reduce"])("não acompanha pointer com preferência %s", (mode) => {
  fine = mode !== "coarse"; reduced = mode === "reduce";
  render(); move(400, 400);
  expect(frames.size).toBe(0);
  expect(art().dataset.tracking).toBeUndefined();
});
it("neutraliza a mudança de preferência e remove listeners ao desmontar", () => {
  render(); move(400, 400); flushFrame();
  reduced = true;
  mediaListeners.forEach((fn) => fn());
  expect(art().style.getPropertyValue("--mineral-x")).toBe("0px");
  move(400, 400);
  expect(frames.size).toBe(0);
  act(() => root.unmount());
  expect(mediaListeners.size).toBe(0);
  move(400, 400);
  expect(frames.size).toBe(0);
  root = createRoot(host);
});
