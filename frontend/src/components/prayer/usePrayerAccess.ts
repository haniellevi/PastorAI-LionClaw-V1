"use client";
import { useEffect, useState } from "react";
import { prayerFetch } from "./api";
/** Server capability; roles/admin shortcuts never grant this screen. */
export function usePrayerAccess(token: string | null): boolean | null {
  const [result, setResult] = useState<{
    token: string;
    allowed: boolean;
  } | null>(null);
  useEffect(() => {
    if (!token) return;
    const abort = new AbortController();
    void prayerFetch<{ allowed: boolean }>(token, "/access", {
      signal: abort.signal,
    })
      .then((r) => {
        if (!abort.signal.aborted)
          setResult({ token, allowed: r.allowed === true });
      })
      .catch(() => {
        if (!abort.signal.aborted) setResult({ token, allowed: false });
      });
    return () => abort.abort();
  }, [token]);
  if (!token) return false;
  return result?.token === token ? result.allowed : null;
}
