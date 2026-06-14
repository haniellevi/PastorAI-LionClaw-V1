/**
 * form-field (componente do contrato 4.3).
 * Composição label + input + helper/erro.
 * Estados: idle, focus (via :focus do CSS), invalid, disabled.
 */
import { useId, type InputHTMLAttributes } from "react";

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
  ...inputProps
}: FieldProps) {
  const id = useId();
  const helperId = `${id}-helper`;
  const errorId = `${id}-error`;
  const invalid = Boolean(error);

  const describedBy = invalid ? errorId : helper ? helperId : undefined;

  return (
    <div className={["field", invalid ? "invalid" : "", className ?? ""].filter(Boolean).join(" ")}>
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        disabled={disabled}
        aria-invalid={invalid || undefined}
        aria-describedby={describedBy}
        {...inputProps}
      />
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
