import { useT } from '../../i18n/I18nContext';

export type LayerFilter = 'all' | 1 | 2;

const options: { value: LayerFilter; labelKey: string }[] = [
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
  return (
    <div className="layer-switch" role="group" aria-label={t('map.layerLabel')}>
      {options.map((option) => (
        <button
          key={String(option.value)}
          type="button"
          className="layer-switch-button"
          aria-pressed={filter === option.value}
          onClick={() => onChange(option.value)}
        >
          {t(option.labelKey)}
        </button>
      ))}
    </div>
  );
};
