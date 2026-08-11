"use client";

/**
 * Botão da fundação (DESIGN.md §8 · Gate 5).
 * action-primary = diamond-700; hover = diamond-900 (regra definitiva).
 * `loading` desabilita, marca aria-busy e mostra o ds-spinner (único uso
 * permitido de animação contínua — feedback de progresso; o bloco global de
 * reduced-motion zera a duração).
 */
import type { ButtonHTMLAttributes } from "react";

export interface DsButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "tertiary" | "danger";
  size?: "md" | "lg";
  loading?: boolean;
  block?: boolean;
}

export function DsButton({
  variant = "primary",
  size = "md",
  loading = false,
  block = false,
  disabled,
  className,
  children,
  "aria-busy": ariaBusy,
  ...rest
}: DsButtonProps) {
  const classes = [
    "ds-btn",
    `ds-btn--${variant}`,
    size === "lg" ? "ds-btn--lg" : null,
    block ? "ds-btn--block" : null,
    loading ? "ds-btn--loading" : null,
    className,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <button
      type="button"
      {...rest}
      className={classes}
      disabled={disabled || loading}
      aria-busy={loading || ariaBusy || undefined}
    >
      {loading ? <span className="ds-spinner" aria-hidden="true" /> : null}
      {children}
    </button>
  );
}
