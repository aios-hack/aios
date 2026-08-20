import { useMemo, useState } from 'react';
import type { WellsFile } from '../../api/types';
import { useDataset } from '../../data';
import { useT } from '../../i18n/I18nContext';
import { useTimeline } from '../../state/TimelineContext';
import { CountMeter } from '../../ui/CountMeter';
import { ViewStatus } from '../../ui/ViewStatus';
import { LayerSwitch, type LayerFilter } from './LayerSwitch';
import { MapLegend } from './MapLegend';
import { rolesAtStep } from './roles';
import { WellsPlot } from './WellsPlot';
import './FieldMap.css';

const FieldMapReady = ({ data }: { data: WellsFile }) => {
  const t = useT();
  const { selectedWell, selectWell, timeline, stepIndex } = useTimeline();
  const [filter, setFilter] = useState<LayerFilter>('all');
  const { wells, grid } = data;

  const shown = useMemo(
    () =>
      filter === 'all'
        ? wells.length
        : wells.filter((well) => well.layers.includes(filter)).length,
    [wells, filter]
  );

  const timelineData = timeline.status === 'ready' ? timeline.data : null;
  const roles = useMemo(
    () => rolesAtStep(timelineData, stepIndex),
    [timelineData, stepIndex]
  );

  const present = useMemo(() => {
    const keys = new Set<string>();
    for (const well of wells) {
      if (filter !== 'all' && !well.layers.includes(filter)) {
        keys.add('dim');
        continue;
      }
      if (well.layers.length > 1) {
        keys.add('both');
      } else if (well.layers[0] === 2) {
        keys.add('layer2');
      } else {
        keys.add('layer1');
      }
    }
    return keys;
  }, [wells, filter]);

  return (
    <section className="field-map">
      <div className="field-map-toolbar">
        <LayerSwitch filter={filter} onChange={setFilter} />
        <CountMeter
          label={t('map.shownLabel')}
          shown={shown}
          total={wells.length}
          ariaLabel={t('map.shown', { shown, total: wells.length })}
        />
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
        <MapLegend present={present} />
      </div>
    </section>
  );
};

export const FieldMap = () => {
  const t = useT();
  const state = useDataset('wells');

  if (state.status === 'loading') {
    return <ViewStatus kind="loading" title={t('map.loading')} />;
  }
  if (state.status === 'error') {
    return <ViewStatus kind="error" title={t('map.error')} hint={t('map.errorHint')} />;
  }
  if (state.data.wells.length === 0) {
    return <ViewStatus kind="empty" title={t('map.empty')} hint={t('map.emptyHint')} />;
  }

  return <FieldMapReady data={state.data} />;
};
