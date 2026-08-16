import { useT } from '../../i18n/I18nContext';
import { SegmentedControl } from '../../ui/SegmentedControl';

export type LayerFilter = 'all' | 1 | 2;

const optionKeys: { value: LayerFilter; labelKey: string }[] = [
  { value: 'all', labelKey: 'map.layer.all' },
  { value: 1, labelKey: 'map.layer.1' },
  { value: 2, labelKey: 'map.layer.2' }
];

interface LayerSwitchProps {
  filter: LayerFilter;
  onChange: (filter: LayerFilter) => void;
}

export const LayerSwitch = ({ filter, onChange }: LayerSwitchProps) => {
  const t = useT();
  const options = optionKeys.map(({ value, labelKey }) => ({
    value,
    label: t(labelKey)
  }));

  return (
    <SegmentedControl
      options={options}
      active={filter}
      label={t('map.layerLabel')}
      onSelect={onChange}
    />
  );
};
