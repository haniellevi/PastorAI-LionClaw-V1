/**
 * form-field (componente do contrato 4.3).
 * Composição label + input + helper/erro.
 * Estados: idle, focus (via :focus do CSS), invalid, disabled.
 */
import { useId, useState, type InputHTMLAttributes } from "react";

import { Icon } from "@/lib/icons";

export interface FieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "id"> {
  label: string;
  helper?: string;
  error?: string;
}

export function Field({
  label,
  helper,
  error,
  className,
  disabled,
  type,
  ...inputProps
}: FieldProps) {
  const id = useId();
  const helperId = `${id}-helper`;
  const errorId = `${id}-error`;
  const invalid = Boolean(error);

  // Campos de senha ganham um botão para revelar/ocultar o texto digitado.
  const isPassword = type === "password";
  const [revealed, setRevealed] = useState(false);
  const inputType = isPassword && revealed ? "text" : type;

  const describedBy = invalid ? errorId : helper ? helperId : undefined;

  const input = (
    <input
      id={id}
      type={inputType}
      disabled={disabled}
      aria-invalid={invalid || undefined}
      aria-describedby={describedBy}
      {...inputProps}
    />
  );

  return (
    <div className={["field", invalid ? "invalid" : "", className ?? ""].filter(Boolean).join(" ")}>
      <label htmlFor={id}>{label}</label>
      {isPassword ? (
        <div className="field-pass">
          {input}
          <button
            type="button"
            className="field-reveal"
            onClick={() => setRevealed((v) => !v)}
            disabled={disabled}
            aria-label={revealed ? "Ocultar senha" : "Mostrar senha"}
            aria-pressed={revealed}
            title={revealed ? "Ocultar senha" : "Mostrar senha"}
          >
            <Icon name={revealed ? "eye-off" : "eye"} size={18} />
          </button>
        </div>
      ) : (
        input
      )}
      {helper && !invalid ? (
        <div className="helper" id={helperId}>
          {helper}
        </div>
      ) : null}
      {invalid ? (
        <div className="err" id={errorId} role="alert">
          {error}
        </div>
      ) : null}
    </div>
  );
}
