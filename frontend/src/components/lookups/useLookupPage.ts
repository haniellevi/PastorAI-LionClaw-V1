"use client";

import { useCallback, useEffect, useState } from "react";
import type { Page } from "@/lib/dashboard-api";

export type LookupLoader<T> = (q: string, page: number, signal: AbortSignal) => Promise<Page<T>>;

export function useLookupPage<T>(loadPage: LookupLoader<T> | undefined, query: string, enabled = true) {
  const [page, setPage] = useState(1);
  const [result, setResult] = useState<Page<T> | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [nonce, setNonce] = useState(0);
  const [requestQuery, setRequestQuery] = useState(query);
  const retry = useCallback(() => setNonce((value) => value + 1), []);
  useEffect(() => { setPage(1); setResult(null); }, [loadPage]);
  useEffect(() => {
    // Initial page starts immediately; edits wait for the user to finish typing.
    if (query === requestQuery) return;
    setLoading(true);
    const timer = window.setTimeout(() => { setPage(1); setRequestQuery(query); }, 250);
    return () => window.clearTimeout(timer);
  }, [query, requestQuery]);
  useEffect(() => {
    if (!loadPage || !enabled || query !== requestQuery) return;
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    void loadPage(requestQuery, page, controller.signal).then(
      (value) => { if (!controller.signal.aborted) setResult(value); },
      (reason: unknown) => { if (!controller.signal.aborted) { setResult(null); setError(reason); } },
    ).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [loadPage, enabled, query, requestQuery, page, nonce]);
  return { result, loading, error, page, setPage, retry };
}
