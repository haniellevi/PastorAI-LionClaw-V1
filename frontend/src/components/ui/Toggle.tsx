/**
 * toggle-switch (componente do contrato 4.3). Switch on/off acessível,
 * portado do artifact travado (.switch > input + .sw-track).
 */
export interface ToggleProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
  disabled?: boolean;
}

export function Toggle({ checked, onChange, label, disabled }: ToggleProps) {
  return (
    <label className="switch" aria-label={label}>
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span className="sw-track" />
    </label>
  );
}
