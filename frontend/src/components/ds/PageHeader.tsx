/**
 * Cabeçalho de página da fundação: eyebrow opcional (context, 12px caps —
 * uso EXCEPCIONAL), UM h1 (--type-h1), sub 14 secundário e slot de ação
 * à direita.
 */
import type { ReactNode } from "react";

export interface DsPageHeaderProps {
  title: string;
  /** Eyebrow de contexto acima do título — uso excepcional. */
  context?: string;
  sub?: string;
  action?: ReactNode;
}

export function DsPageHeader({ title, context, sub, action }: DsPageHeaderProps) {
  return (
    <header className="ds-pageheader">
      <div>
        {context ? <p className="ds-pageheader-eyebrow">{context}</p> : null}
        <h1 className="ds-pageheader-title">{title}</h1>
        {sub ? <p className="ds-pageheader-sub">{sub}</p> : null}
      </div>
      {action ? <div className="ds-pageheader-action">{action}</div> : null}
    </header>
  );
}
