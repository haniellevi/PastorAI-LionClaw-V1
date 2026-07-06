"use client";

/**
 * Tela "Integrações" da superfície admin (admin.<domínio> → /gestao).
 * Reúne a configuração administrativa da Agenda que antes vivia embutida na
 * tela operacional (#calendario): conexão com o Google Agenda e destinatários
 * dos avisos. Os componentes de card são reusados como estão (auto-gated por
 * admin); nada de lógica nova. Eventos importados caem em "A confirmar" na
 * Agenda operacional (app), onde pastor/admin confirmam.
 */
import { useState } from "react";

import { AlertRecipientsCard } from "@/components/calendario/AlertRecipientsCard";
import { CalendarConnectCard } from "@/components/calendario/CalendarConnectCard";
import type { ImportResult } from "@/lib/calendar-api";

export function IntegracoesScreen() {
  const [msg, setMsg] = useState<string | null>(null);

  return (
    <div className="screen" key="integracoes">
      {msg ? (
        <div className="info-banner" role="status">
          {msg}
        </div>
      ) : null}

      <CalendarConnectCard
        onImported={(r: ImportResult) =>
          setMsg(
            r.created > 0
              ? `${r.created} evento(s) importado(s)${r.skipped ? ` · ${r.skipped} ignorado(s)` : ""}. Confirme na Agenda, aba "A confirmar".`
              : r.skipped
                ? `Nada novo: ${r.skipped} evento(s) já existentes.`
                : "Nenhum evento novo no Google.",
          )
        }
      />
      <AlertRecipientsCard />
    </div>
  );
}
