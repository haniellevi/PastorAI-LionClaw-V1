/**
 * btn-primary (componente do contrato 4.3).
 * Variantes: primary | default | ghost | danger.
 * Estados: default, hover, loading (spinner + aria-busy), disabled.
 * Estilos vêm de globals.css (.btn / .btn-primary…), portados do artifact.
 */
import type { ButtonHTMLAttributes, ReactNode } from "react";

type Variant = "primary" | "default" | "ghost" | "danger";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  loading?: boolean;
  loadingText?: string;
  block?: boolean;
  size?: "md" | "sm";
  children: ReactNode;
}

const VARIANT_CLASS: Record<Variant, string> = {
  primary: "btn-primary",
  default: "",
  ghost: "btn-ghost",
  danger: "btn-danger",
};

export function Button({
  variant = "default",
  loading = false,
  loadingText,
  block = false,
  size = "md",
  disabled,
  className,
  children,
  type = "button",
  ...rest
}: ButtonProps) {
  const classes = [
    "btn",
    VARIANT_CLASS[variant],
    block ? "btn-block" : "",
    size === "sm" ? "btn-sm" : "",
    className ?? "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <button
      type={type}
      className={classes}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      {loading ? (
        <>
          <span className="spinner" aria-hidden="true" />
          <span>{loadingText ?? "Carregando…"}</span>
        </>
      ) : (
        children
      )}
    </button>
  );
}
