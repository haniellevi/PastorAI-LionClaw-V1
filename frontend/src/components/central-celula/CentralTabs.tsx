"use client";

/**
 * CentralTabs — as 5 abas da Central de Célula (Dashboard, Gerenciar células,
 * Solicitações, Avisos, Materiais). O strip rola na horizontal quando não cabe
 * (`.central-tabs`), sem vazar a página em 360px. Reusa `.tabs/.tab` do tema.
 * Badges numéricos (pendências) destacam abas que exigem ação.
 */
import type { CentralTab } from "./types";

interface TabDef {
  id: CentralTab;
  label: string;
}

const TABS: TabDef[] = [
  { id: "dashboard", label: "Dashboard" },
  { id: "cells", label: "Gerenciar células" },
  { id: "requests", label: "Solicitações" },
  { id: "notices", label: "Avisos" },
  { id: "materials", label: "Materiais" },
];

export function CentralTabs({
  active,
  onChange,
  badges,
}: {
  active: CentralTab;
  onChange: (tab: CentralTab) => void;
  /** Contadores por aba (ex.: solicitações aguardando). */
  badges?: Partial<Record<CentralTab, number>>;
}) {
  return (
    <div className="central-tabs">
      <div className="tabs" role="tablist" aria-label="Central de Célula">
        {TABS.map((t) => {
          const count = badges?.[t.id] ?? 0;
          const isActive = active === t.id;
          return (
            <button
              key={t.id}
              type="button"
              role="tab"
              aria-selected={isActive}
              className={`tab${isActive ? " active" : ""}`}
              onClick={() => onChange(t.id)}
            >
              {t.label}
              {count > 0 ? <span className="num"> {count}</span> : null}
            </button>
          );
        })}
      </div>
    </div>
  );
}
