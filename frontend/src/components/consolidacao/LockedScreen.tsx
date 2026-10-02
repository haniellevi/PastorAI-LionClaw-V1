"use client";

import "@/components/config/administration-ux-v2.css";

import { Icon } from "@/lib/icons";

type LockedVariant = "universidade-vida" | "capacitacao";

const TITLES: Record<LockedVariant, string> = {
  "universidade-vida": "Universidade da Vida",
  capacitacao: "Capacitação Destino",
};

/** Apresentação do bloqueio existente. Não consulta API nem simula formação. */
export function LockedScreen({ variant }: { variant: LockedVariant }) {
  const title = TITLES[variant];
  return (
    <div className="screen journey-screen locked-screen administration-ux" key={variant}>
      <div className="screen-head">
        <div className="titles">
          <h2>{title}</h2>
          <p>Este módulo ainda não está disponível no painel.</p>
        </div>
      </div>
      <div className="card card-pad admin-unavailable" role="status">
        <div className="panel-title"><Icon name="lock" /> Módulo indisponível</div>
        <p>Turmas, presença e certificação não podem ser registradas nesta área.</p>
        <a className="btn btn-primary" href="#dashboard" style={{ marginTop: "var(--s4)" }}>Voltar ao Hoje</a>
      </div>
    </div>
  );
}
