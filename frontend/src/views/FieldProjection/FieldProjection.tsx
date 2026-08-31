import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { GraphFile, WellsFile } from '../../api/types';
import { useDataset } from '../../data';
import { useT } from '../../i18n/I18nContext';
import { useMorphRequest } from '../../state/ConsoleContext';
import { useTimeline } from '../../state/TimelineContext';
import { ViewStatus } from '../../ui/ViewStatus';
import { formatWindowDate } from '../shared/graphModel';
import { useSelectionHighlight } from '../WellCard/useSelectionHighlight';
import { EdgeLayer } from './EdgeLayer';
import type { PlacedNode } from './interpolate';
import { dimmedWellIds, shownCount, type LayerFilter } from './layerFilter';
import { useProjectionGeometry, useWellStates } from './model';
import { NodeLayer } from './NodeLayer';
import { ProjectionControls, type ProjectionPole } from './ProjectionControls';
import { usePlotGestures, useProjectionTravel } from './useProjection';
import './FieldProjection.css';

interface ReadyProps {
  wells: WellsFile;
  graph: GraphFile;
}

const FieldProjectionReady = ({ wells, graph }: ReadyProps) => {
  const t = useT();
  const { selectedWell, selectWell } = useTimeline();
  const morphRequest = useMorphRequest();
  const [pole, setPole] = useState<ProjectionPole>('graph');
  const [threshold, setThreshold] = useState<number | null>(null);
  const [layerFilter, setLayerFilter] = useState<LayerFilter>('all');
  const { t: blend, travelTo } = useProjectionTravel(1);
  const { svgRef, viewBox, scale, unitsPerPixel, handlers, hasDragged } = usePlotGestures();
  const geometry = useProjectionGeometry(wells, graph, blend, threshold);
  const states = useWellStates();
  const highlight = useSelectionHighlight();
  const dimmedIds = useMemo(() => dimmedWellIds(wells, layerFilter), [wells, layerFilter]);
  const isDimmed = useCallback((id: string) => dimmedIds.has(id), [dimmedIds]);
  const shown = useMemo(() => shownCount(wells, layerFilter), [wells, layerFilter]);

  const titleOf = useCallback(
    (node: PlacedNode) =>
      node.onlyMap ? `${node.id} · ${t('projection.node.noConnectivity')}` : node.id,
    [t]
  );

  const onPole = useCallback(
    (next: ProjectionPole) => {
      setPole(next);
      travelTo(next === 'map' ? 0 : 1);
    },
    [travelTo]
  );

  const servedMorph = useRef<number | null>(null);

  useEffect(() => {
    if (morphRequest === null || servedMorph.current === morphRequest.serial) {
      return;
    }
    servedMorph.current = morphRequest.serial;
    setPole(morphRequest.value >= 0.5 ? 'graph' : 'map');
    travelTo(morphRequest.value);
  }, [morphRequest, travelTo]);

  const onSelectWell = useCallback(
    (well: string) => {
      if (hasDragged()) {
        return;
      }
      selectWell(well);
    },
    [hasDragged, selectWell]
  );

  return (
    <section className="field-projection">
      <ProjectionControls
        pole={pole}
        threshold={geometry.activeThreshold}
        thresholdMin={geometry.bounds.min}
        thresholdMax={geometry.bounds.max}
        shownEdges={geometry.edges.length}
        totalEdges={graph.edges.length}
        layers={wells.layers}
        layerFilter={layerFilter}
        onPole={onPole}
        onThreshold={setThreshold}
        onLayerFilter={setLayerFilter}
        legendNotes={[
          {
            text: t('projection.shown', { shown, total: wells.wells.length }),
            testId: 'field-projection-shown'
          },
          {
            text: t('projection.withoutConnectivity', { count: geometry.withoutConnectivity }),
            testId: 'field-projection-orphans'
          },
          {
            text: t('projection.window', {
              start: formatWindowDate(graph.window.start),
              end: formatWindowDate(graph.window.end)
            }),
            testId: 'field-projection-window'
          },
          ...(layerFilter !== 'all'
            ? [{ text: t('projection.dim'), testId: 'field-projection-dim' }]
            : [])
        ]}
      />
      <div className="field-projection-canvas">
        <svg
          ref={svgRef}
          className="field-projection-plot"
          viewBox={`${viewBox.x} ${viewBox.y} ${viewBox.width} ${viewBox.height}`}
          role="img"
          aria-label={t('projection.ariaLabel')}
          data-testid="field-projection-plot"
          {...handlers}
        >
          <EdgeLayer
            edges={geometry.edges}
            placed={geometry.placedIndex}
            maxWeight={graph.weight_range.max}
            t={blend}
            scale={scale}
            selectedWell={selectedWell}
          />
          <NodeLayer
            placed={geometry.placed}
            states={states}
            selectedWell={selectedWell}
            highlight={highlight}
            titleOf={titleOf}
            scale={scale}
            unitsPerPixel={unitsPerPixel}
            isDimmed={isDimmed}
            onSelectWell={onSelectWell}
          />
        </svg>
      </div>
    </section>
  );
};

export const FieldProjection = () => {
  const t = useT();
  const wells = useDataset('wells');
  const graph = useDataset('graph');

  if (wells.status === 'loading' || graph.status === 'loading') {
    return <ViewStatus kind="loading" title={t('projection.loading')} />;
  }
  if (wells.status === 'error' || graph.status === 'error') {
    return (
      <ViewStatus
        kind="error"
        title={t('projection.error')}
        hint={t('projection.errorHint')}
      />
    );
  }
  if (wells.data.wells.length === 0 && graph.data.nodes.length === 0) {
    return (
      <ViewStatus
        kind="empty"
        title={t('projection.empty')}
        hint={t('projection.emptyHint')}
      />
    );
  }

  return <FieldProjectionReady wells={wells.data} graph={graph.data} />;
};
