"use client";

import { useEffect, useRef } from "react";

/** Visible polling coalesces in-flight work; failed callbacks back off with jitter. */
export function useVisibleInterval(callback: () => void | Promise<unknown>, intervalMs: number, enabled = true): void {
  const latest = useRef(callback);
  useEffect(() => { latest.current = callback; }, [callback]);
  useEffect(() => {
    if (!enabled) return;
    let timer: ReturnType<typeof setInterval> | undefined;
    let hidden = document.visibilityState === "hidden";
    let disposed = false;
    let pending = false;
    let failures = 0;
    let retryAfter = 0;
    const stop = () => { if (timer !== undefined) clearInterval(timer); timer = undefined; };
    const failed = () => { failures += 1; retryAfter = Date.now() + intervalMs * 2 ** Math.min(failures,3) + Math.round(Math.random() * intervalMs * .1); };
    const run = () => {
      if (disposed || hidden || pending || Date.now() < retryAfter) return;
      try {
        const result = latest.current();
        if (result && typeof result.then === "function") {
          pending = true;
          result.then(() => { failures = 0; retryAfter = 0; }, failed).finally(() => { pending = false; });
        } else { failures = 0; retryAfter = 0; }
      } catch { failed(); }
    };
    const start = () => { stop(); timer = setInterval(run,intervalMs); };
    const visibility = () => {
      const nextHidden = document.visibilityState === "hidden";
      if (nextHidden === hidden) return;
      hidden = nextHidden;
      if (hidden) stop();
      else { retryAfter = 0; run(); start(); }
    };
    if (!hidden) start();
    document.addEventListener("visibilitychange", visibility);
    return () => { disposed = true; stop(); document.removeEventListener("visibilitychange", visibility); };
  }, [intervalMs, enabled]);
}
