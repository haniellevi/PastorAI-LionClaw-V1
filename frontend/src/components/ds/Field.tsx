/**
 * Campo de formulário da fundação: label SEMPRE visível acima (nunca
 * placeholder-como-label); helper 12px abaixo; erro troca o helper por
 * mensagem com role="alert" + aria-invalid/aria-describedby no controle.
 */
import {
  createElement,
  useId,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";

type ControlNative = InputHTMLAttributes<HTMLInputElement> &
  SelectHTMLAttributes<HTMLSelectElement> &
  TextareaHTMLAttributes<HTMLTextAreaElement>;

export interface DsFieldProps extends Omit<ControlNative, "children"> {
  label: string;
  helper?: string;
  /** Presente = estado de erro (substitui o helper). */
  error?: string;
  as?: "input" | "select" | "textarea";
  /** Options, quando as="select". */
  children?: ReactNode;
}

export function DsField({
  label,
  helper,
  error,
  as = "input",
  id,
  children,
  className,
  ...rest
}: DsFieldProps) {
  const autoId = useId();
  const controlId = id ?? autoId;
  const msgId = `${controlId}-msg`;
  const invalid = Boolean(error);

  const control = createElement(
    as,
    {
      ...rest,
      id: controlId,
      className: [invalid ? "ds-input ds-input--error" : "ds-input", className]
        .filter(Boolean)
        .join(" "),
      "aria-invalid": invalid || undefined,
      "aria-describedby": error || helper ? msgId : undefined,
    },
    as === "select" ? children : undefined,
  );

  return (
    <div className="ds-field">
      <label className="ds-field-label" htmlFor={controlId}>
        {label}
      </label>
      {control}
      {error ? (
        <p id={msgId} className="ds-field-error" role="alert">
          {error}
        </p>
      ) : helper ? (
        <p id={msgId} className="ds-field-help">
          {helper}
        </p>
      ) : null}
    </div>
  );
}
