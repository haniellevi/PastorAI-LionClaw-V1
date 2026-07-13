"use client";

/**
 * Botão de ícone da fundação: rótulo acessível OBRIGATÓRIO (vira aria-label
 * + title) e alvo mínimo de 44×44 (classe ds-iconbtn, definida em ds.css).
 */
import type { ButtonHTMLAttributes, ReactNode } from "react";

export interface DsIconButtonProps
  extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "aria-label" | "title" | "children"> {
  /** Rótulo acessível do botão (o ícone é decorativo). */
  label: string;
  /** Ícone svg. */
  children: ReactNode;
}

export function DsIconButton({ label, className, children, ...rest }: DsIconButtonProps) {
  return (
    <button
      type="button"
      {...rest}
      aria-label={label}
      title={label}
      className={className ? `ds-iconbtn ${className}` : "ds-iconbtn"}
    >
      {children}
    </button>
  );
}
