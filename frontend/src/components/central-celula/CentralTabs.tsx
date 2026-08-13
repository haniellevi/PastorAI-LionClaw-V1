"use client";

/**
 * CentralTabs — as 5 abas da Central de Célula (Dashboard, Gerenciar células,
 * Solicitações, Avisos, Materiais), sobre o primitive `Tabs` da fundação
 * (roving focus, overflow-x real com véu/chevron, alvo ≥44px). Badges
 * numéricos (pendências) destacam abas que exigem ação.
 */
import type { ReactNode } from "react";

import { Tabs } from "@/components/ds/Tabs";
import type { CentralTab } from "./types";

interface TabDef {
  id: CentralTab;
  label: string;
}

const TABS: TabDef[] = [
  { id: "dashboard", label: "Hoje" },
  { id: "cells", label: "Gerenciar células" },
  { id: "requests", label: "Solicitações" },
  { id: "notices", label: "Avisos" },
  { id: "materials", label: "Materiais" },
];

export function CentralTabs({
  active,
  onChange,
  badges,
  children,
}: {
  active: CentralTab;
  onChange: (tab: CentralTab) => void;
  /** Contadores por aba (ex.: solicitações aguardando). */
  badges?: Partial<Record<CentralTab, number>>;
  children?: ReactNode;
}) {
  return (
    <Tabs
      tabs={TABS.map((t) => ({ id: t.id, label: t.label, badge: badges?.[t.id] || undefined }))}
      active={active}
      onChange={(id) => onChange(id as CentralTab)}
      label="Central de Célula"
    >
      {children}
    </Tabs>
  );
}
