"use client";

import type { Page } from "@/lib/dashboard-api";
import { DsButton } from "@/components/ds/Button";

export function LookupPager({ result, loading, onPage }: {
  result: Page<unknown> | null; loading: boolean; onPage: (page: number) => void;
}) {
  if (!result) return null;
  const pages = Math.max(1, Math.ceil(result.total / result.pageSize));
  return <div className="lookup-pagination" style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginTop: 8 }}>
    <span className="sub" role="status">{result.total} resultados · Página {result.page} de {pages}</span>
    {pages > 1 ? <>
      <DsButton variant="secondary" disabled={loading || result.page <= 1} onClick={() => onPage(result.page - 1)}>Página anterior</DsButton>
      <DsButton variant="secondary" disabled={loading || result.page >= pages} onClick={() => onPage(result.page + 1)}>Próxima página</DsButton>
    </> : null}
  </div>;
}
