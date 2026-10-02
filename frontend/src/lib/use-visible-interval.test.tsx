// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { useVisibleInterval } from "./use-visible-interval";

it("pausa aba oculta, retoma exatamente uma vez e limpa no unmount", () => {
  vi.useFakeTimers();
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  let visibility = "visible";
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => visibility });
  const poll = vi.fn();
  function Probe() { useVisibleInterval(poll, 15_000); return null; }
  const root = createRoot(document.createElement("div"));
  act(() => root.render(<Probe />));
  act(() => vi.advanceTimersByTime(15_000));
  expect(poll).toHaveBeenCalledTimes(1);
  visibility = "hidden";
  act(() => document.dispatchEvent(new Event("visibilitychange")));
  act(() => vi.advanceTimersByTime(90_000));
  expect(poll).toHaveBeenCalledTimes(1);
  visibility = "visible";
  act(() => document.dispatchEvent(new Event("visibilitychange")));
  act(() => document.dispatchEvent(new Event("visibilitychange")));
  expect(poll).toHaveBeenCalledTimes(2);
  act(() => root.unmount());
  act(() => vi.advanceTimersByTime(90_000));
  expect(poll).toHaveBeenCalledTimes(2);
  Reflect.deleteProperty(document, "visibilityState");
  vi.useRealTimers();
});
