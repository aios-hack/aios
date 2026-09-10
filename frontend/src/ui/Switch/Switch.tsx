import './Switch.css';

interface SwitchProps {
  id?: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  label?: string;
  guide?: string;
  testId?: string;
}

export const Switch = ({ id, checked, onChange, label, guide, testId }: SwitchProps) => (
  <span className="ui-switch">
    <input
      id={id}
      type="checkbox"
      className="ui-switch-input"
      checked={checked}
      aria-label={label}
      data-guide={guide}
      data-testid={testId}
      onChange={(event) => onChange(event.target.checked)}
    />
    <span className="ui-switch-track" aria-hidden="true">
      <span className="ui-switch-thumb" />
    </span>
  </span>
);
