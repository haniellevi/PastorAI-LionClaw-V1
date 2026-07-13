/**
 * Estado vazio da fundação: centrado, ilustração opcional em cima,
 * título 16/650, hint 14 secundário, ação embaixo. Sem heading fixo
 * (o nível de título é da tela, não do primitive).
 */
import type { ReactNode } from "react";

export interface DsEmptyStateProps {
  title: string;
  hint?: string;
  action?: ReactNode;
  illustration?: ReactNode;
}

export function DsEmptyState({ title, hint, action, illustration }: DsEmptyStateProps) {
  return (
    <div className="ds-empty">
      {illustration ? (
        <div className="ds-empty-illustration" aria-hidden="true">
          {illustration}
        </div>
      ) : null}
      <p className="ds-empty-title">{title}</p>
      {hint ? <p className="ds-empty-hint">{hint}</p> : null}
      {action ? <div className="ds-empty-action">{action}</div> : null}
    </div>
  );
}
