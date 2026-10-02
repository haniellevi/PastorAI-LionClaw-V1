"use client";

import "@/components/config/administration-ux-v2.css";

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
    <div className="screen admin-screen integrations-screen administration-ux" key="integracoes">
      <div className="screen-head">
        <div className="titles">
          <h2>Integrações</h2>
          <p>Conecte o calendário e defina quem recebe os alertas da igreja.</p>
        </div>
      </div>
      {msg ? (
        <div className="info-banner" role="status">
          {msg}
        </div>
      ) : null}

      <section className="admin-section" aria-labelledby="calendar-connection-title">
      <h3 id="calendar-connection-title">Conta e importação</h3>
      <p className="sub">Conectar o Google autoriza a integração. Eventos importados precisam de confirmação na Agenda.</p>
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
      </section>
      <section className="admin-section" aria-labelledby="calendar-alert-title">
      <h3 id="calendar-alert-title">Quem recebe os alertas</h3>
      <AlertRecipientsCard />
      </section>
    </div>
  );
}
