import { useEffect, useState } from 'react';
import type { WellsFile } from '../../api/types';
import { useT } from '../../i18n/I18nContext';
import { layerColors } from '../../theme/tokens';
import { LayerSwitch, type LayerFilter } from './LayerSwitch';
import { WellsPlot } from './WellsPlot';
import './FieldMap.css';

type LoadState =
  | { status: 'loading' }
  | { status: 'error' }
  | { status: 'ready'; data: WellsFile };

const legendItems = [
  { labelKey: 'map.legend.layer1', color: layerColors.layer1 },
  { labelKey: 'map.legend.layer2', color: layerColors.layer2 },
  { labelKey: 'map.legend.both', color: layerColors.both },
  { labelKey: 'map.legend.dim', color: layerColors.dim }
];

export const FieldMap = () => {
  const t = useT();
  const [state, setState] = useState<LoadState>({ status: 'loading' });
  const [filter, setFilter] = useState<LayerFilter>('all');

  useEffect(() => {
    let cancelled = false;
    fetch('/data/wells.json')
      .then((response) => {
        if (!response.ok) {
          throw new Error(String(response.status));
        }
        return response.json();
      })
      .then((data: WellsFile) => {
        if (!cancelled) {
          setState({ status: 'ready', data });
        }
      })
      .catch(() => {
        if (!cancelled) {
          setState({ status: 'error' });
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (state.status === 'loading') {
    return <p className="field-map-status">{t('map.loading')}</p>;
  }
  if (state.status === 'error') {
    return <p className="field-map-status field-map-error">{t('map.error')}</p>;
  }

  const { wells, grid } = state.data;
  const shown =
    filter === 'all' ? wells.length : wells.filter((well) => well.layers.includes(filter)).length;

  return (
    <section className="field-map">
      <div className="field-map-toolbar">
        <LayerSwitch filter={filter} onChange={setFilter} />
        <span className="field-map-count">
          {t('map.shown', { shown, total: wells.length })}
        </span>
      </div>
      <WellsPlot wells={wells} grid={grid} filter={filter} />
      <p className="field-map-axes">{t('map.axes', { ni: grid.ni, nj: grid.nj })}</p>
      <ul className="field-map-legend">
        {legendItems.map((item) => (
          <li key={item.labelKey} className="field-map-legend-item">
            <span className="field-map-swatch" style={{ background: item.color }} />
            {t(item.labelKey)}
          </li>
        ))}
      </ul>
    </section>
  );
};
