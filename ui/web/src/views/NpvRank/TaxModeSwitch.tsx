import { useT } from '../../i18n/I18nContext';
import type { TaxMode } from './types';

interface TaxModeSwitchProps {
  mode: TaxMode;
  onChange: (mode: TaxMode) => void;
}

const MODES: TaxMode[] = ['preTax', 'withTax'];

export const TaxModeSwitch = ({ mode, onChange }: TaxModeSwitchProps) => {
  const t = useT();

  return (
    <div className="npv-mode" role="group" aria-label={t('npv.mode.legend')}>
      {MODES.map((value) => (
        <button
          key={value}
          type="button"
          className="npv-mode-button"
          aria-pressed={mode === value}
          onClick={() => onChange(value)}
        >
          {t(`npv.mode.${value}`)}
        </button>
      ))}
    </div>
  );
};
