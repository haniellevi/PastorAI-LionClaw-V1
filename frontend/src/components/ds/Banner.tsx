/**
 * Banner de contexto da fundação. Fundo soft + texto no tom forte do estado;
 * borda 1px completa (border-left grossa é proibida). `error` = role="alert";
 * demais = role="status". `degraded` reusa o soft de warning com ícone próprio.
 */
import type { ReactNode } from "react";

export type DsBannerKind = "info" | "warning" | "error" | "degraded";

export interface DsBannerProps {
  kind: DsBannerKind;
  children: ReactNode;
  /** Ação opcional à direita (ex.: botão tentar de novo). */
  action?: ReactNode;
}

const ICONS: Record<DsBannerKind, ReactNode> = {
  info: (
    <svg viewBox="0 0 20 20" width="18" height="18">
      <circle cx="10" cy="10" r="8.25" fill="none" stroke="currentColor" strokeWidth="1.5" />
      <path d="M10 9v5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      <circle cx="10" cy="6.2" r="0.9" fill="currentColor" />
    </svg>
  ),
  warning: (
    <svg viewBox="0 0 20 20" width="18" height="18">
      <path d="M10 2.6L18.6 17H1.4L10 2.6z" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
      <path d="M10 8v4.2" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      <circle cx="10" cy="14.7" r="0.9" fill="currentColor" />
    </svg>
  ),
  error: (
    <svg viewBox="0 0 20 20" width="18" height="18">
      <circle cx="10" cy="10" r="8.25" fill="none" stroke="currentColor" strokeWidth="1.5" />
      <path d="M7 7l6 6M13 7l-6 6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  ),
  // Degradação parcial: círculo tracejado (serviço "meio conectado").
  degraded: (
    <svg viewBox="0 0 20 20" width="18" height="18">
      <circle cx="10" cy="10" r="8.25" fill="none" stroke="currentColor" strokeWidth="1.5" strokeDasharray="3.4 2.6" />
      <path d="M10 6.5v4l2.6 1.8" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ),
};

export function DsBanner({ kind, children, action }: DsBannerProps) {
  return (
    <div className={`ds-banner ds-banner--${kind}`} role={kind === "error" ? "alert" : "status"}>
      <span className="ds-banner-icon" aria-hidden="true">
        {ICONS[kind]}
      </span>
      <div className="ds-banner-body">{children}</div>
      {action ? <div className="ds-banner-action">{action}</div> : null}
    </div>
  );
}
