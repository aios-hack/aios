import { useT } from '../../i18n/I18nContext';
import { SegmentedControl } from '../../ui/SegmentedControl';
import type { TaxMode } from './types';

interface TaxModeSwitchProps {
  mode: TaxMode;
  onChange: (mode: TaxMode) => void;
}

const MODES: TaxMode[] = ['preTax', 'withTax'];

export const TaxModeSwitch = ({ mode, onChange }: TaxModeSwitchProps) => {
  const t = useT();
  const options = MODES.map((value) => ({ value, label: t(`npv.mode.${value}`) }));

  return (
    <SegmentedControl
      options={options}
      active={mode}
      label={t('npv.mode.legend')}
      guide="npv-tax-mode"
      onSelect={onChange}
    />
  );
};
