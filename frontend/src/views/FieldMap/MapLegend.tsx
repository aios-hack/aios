import { memo } from 'react';
import { useT } from '../../i18n/I18nContext';
import { layerColors } from '../../theme/tokens';

const layerItems = [
  { key: 'layer1', labelKey: 'map.legend.layer1', color: layerColors.layer1 },
  { key: 'layer2', labelKey: 'map.legend.layer2', color: layerColors.layer2 },
  { key: 'both', labelKey: 'map.legend.both', color: layerColors.both },
  { key: 'dim', labelKey: 'map.legend.dim', color: layerColors.dim }
];

interface MapLegendProps {
  present: Set<string>;
}

const MapLegendView = ({ present }: MapLegendProps) => {
  const t = useT();
  const shownItems = layerItems.filter((item) => present.has(item.key));

  return (
    <div className="map-legend" role="group" aria-label={t('map.legend.title')}>
      <p className="map-legend-title">{t('map.legend.title')}</p>
      <ul className="map-legend-list">
        {shownItems.map((item) => (
          <li key={item.labelKey} className="map-legend-item">
            <span
              className="map-legend-swatch"
              data-swatch={item.key}
              style={{ background: item.color }}
            />
            {t(item.labelKey)}
          </li>
        ))}
      </ul>
      <p className="map-legend-title">{t('map.legend.shape')}</p>
      <ul className="map-legend-list">
        <li className="map-legend-item">
          <svg className="map-legend-glyph" viewBox="0 0 12 12" aria-hidden="true">
            <circle cx="6" cy="6" r="4" fill="currentColor" />
          </svg>
          {t('map.legend.producer')}
        </li>
        <li className="map-legend-item">
          <svg className="map-legend-glyph" viewBox="0 0 12 12" aria-hidden="true">
            <path d="M 6 11 L 11 3 L 1 3 Z" fill="currentColor" />
          </svg>
          {t('map.legend.injector')}
        </li>
      </ul>
    </div>
  );
};

export const MapLegend = memo(MapLegendView);
