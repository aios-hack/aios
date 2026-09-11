import type { ReactNode } from 'react';
import './SettingsField.css';

interface SettingsFieldProps {
  htmlFor: string;
  label: string;
  value: string;
  valueTestId?: string;
  children: ReactNode;
}

export const SettingsField = ({
  htmlFor,
  label,
  value,
  valueTestId,
  children
}: SettingsFieldProps) => (
  <div className="settings-field">
    <div className="settings-field-head">
      <label className="settings-field-label" htmlFor={htmlFor}>
        {label}
      </label>
      <output className="settings-field-value" htmlFor={htmlFor} data-testid={valueTestId}>
        {value}
      </output>
    </div>
    {children}
  </div>
);
