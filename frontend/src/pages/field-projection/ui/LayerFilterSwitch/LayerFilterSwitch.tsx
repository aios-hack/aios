import type { LayerRange } from '@/entities/wells/types';
import { useT } from '@/shared/i18n/I18nContext';
import { SegmentedControl } from '@/shared/ui/SegmentedControl';
import { layerOptions, type LayerFilter } from '@/pages/field-projection/model/layerFilter';

interface LayerFilterSwitchProps {
  layers: LayerRange[];
  filter: LayerFilter;
  onChange: (filter: LayerFilter) => void;
}

export const LayerFilterSwitch = ({ layers, filter, onChange }: LayerFilterSwitchProps) => {
  const t = useT();
  const options = layerOptions(layers).map((option) => ({
    value: option.value,
    label: option.id === null ? t('projection.layer.all') : t('projection.layer.item', { id: option.id })
  }));

  return (
    <SegmentedControl
      options={options}
      active={filter}
      label={t('projection.layerLabel')}
      guide="projection-layer-switch"
      onSelect={onChange}
    />
  );
};
