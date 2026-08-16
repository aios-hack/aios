import { useState } from 'react';
import { useDataset } from '../../data';
import { useT } from '../../i18n/I18nContext';
import { useTimeline } from '../../state/TimelineContext';
import { ViewStatus } from '../../ui/ViewStatus';
import { LayerSwitch, type LayerFilter } from './LayerSwitch';
import { MapLegend } from './MapLegend';
import { rolesAtStep } from './roles';
import { ShownCounter } from './ShownCounter';
import { WellsPlot } from './WellsPlot';
import './FieldMap.css';

export const FieldMap = () => {
  const t = useT();
  const { selectedWell, selectWell, timeline, stepIndex } = useTimeline();
  const state = useDataset('wells');
  const [filter, setFilter] = useState<LayerFilter>('all');

  if (state.status === 'loading') {
    return <ViewStatus kind="loading" title={t('map.loading')} />;
  }
  if (state.status === 'error') {
    return <ViewStatus kind="error" title={t('map.error')} hint={t('map.errorHint')} />;
  }

  const { wells, grid } = state.data;
  const shown =
    filter === 'all'
      ? wells.length
      : wells.filter((well) => well.layers.includes(filter)).length;
  const roles = rolesAtStep(timeline.status === 'ready' ? timeline.data : null, stepIndex);

  return (
    <section className="field-map">
      <div className="field-map-toolbar">
        <LayerSwitch filter={filter} onChange={setFilter} />
        <ShownCounter shown={shown} total={wells.length} />
      </div>
      <div className="field-map-canvas">
        <WellsPlot
          wells={wells}
          grid={grid}
          filter={filter}
          roles={roles}
          selectedWell={selectedWell}
          onSelectWell={selectWell}
        />
        <MapLegend />
      </div>
    </section>
  );
};
