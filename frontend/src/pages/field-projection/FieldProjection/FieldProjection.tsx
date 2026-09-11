import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { GraphFile } from '@/entities/graph/types';
import type { WellsFile } from '@/entities/wells/types';
import { useDataset } from '@/entities';
import { useT } from '@/shared/i18n/I18nContext';
import { useMorphRequest } from '@/shared/lib/morph';
import { useTimeline } from '@/entities/timeline/model/TimelineContext';
import { ViewStatus } from '@/shared/ui/ViewStatus';
import { formatWindowDate } from '@/entities/graph/model/graphModel';
import { useSelectionHighlight } from '@/entities/wells/model/useSelectionHighlight';
import { EdgeLayer } from '@/pages/field-projection/EdgeLayer/EdgeLayer';
import type { PlacedNode } from '@/entities/graph/model/interpolate';
import { dimmedWellIds, shownCount, type LayerFilter } from '@/pages/field-projection/layerFilter';
import { useProjectionGeometry, useWellStates } from '@/entities/graph/model/projection';
import { NodeLayer } from '@/pages/field-projection/NodeLayer/NodeLayer';
import { NodeTooltip, type NodeHover } from '@/pages/field-projection/NodeTooltip/NodeTooltip';
import { ProjectionControls, type ProjectionPole } from '@/pages/field-projection/ProjectionControls/ProjectionControls';
import { usePlotGestures, useProjectionTravel } from '@/entities/graph/model/useProjection';
import './FieldProjection.css';

const TOOLTIP_GRACE_MS = 220;

interface ReadyProps {
  wells: WellsFile;
  graph: GraphFile;
}

const FieldProjectionReady = ({ wells, graph }: ReadyProps) => {
  const t = useT();
  const { selectedWell, selectWell, stepIndex } = useTimeline();
  const morphRequest = useMorphRequest();
  const [pole, setPole] = useState<ProjectionPole>('graph');
  const [threshold, setThreshold] = useState<number | null>(null);
  const [layerFilter, setLayerFilter] = useState<LayerFilter>('all');
  const [showGroups, setShowGroups] = useState(false);
  const [hover, setHover] = useState<NodeHover | null>(null);
  const hoverTimer = useRef<number | null>(null);
  const holdHover = useCallback((next: NodeHover | null) => {
    if (hoverTimer.current !== null) {
      clearTimeout(hoverTimer.current);
      hoverTimer.current = null;
    }
    if (next !== null) {
      setHover(next);
      return;
    }
    hoverTimer.current = window.setTimeout(() => setHover(null), TOOLTIP_GRACE_MS);
  }, []);
  const keepHover = useCallback(() => {
    if (hoverTimer.current !== null) {
      clearTimeout(hoverTimer.current);
      hoverTimer.current = null;
    }
  }, []);
  const canvasRef = useRef<HTMLDivElement>(null);
  const [canvasBox, setCanvasBox] = useState({ width: 0, height: 0 });
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

  const onClearSelection = useCallback(() => {
    if (hasDragged()) {
      return;
    }
    selectWell(null);
  }, [hasDragged, selectWell]);

  const rowOf = useCallback(
    (well: string) => states.get(well)?.row,
    [states]
  );

  useEffect(() => {
    const canvas = canvasRef.current;
    if (canvas === null) {
      return;
    }
    const measure = () =>
      setCanvasBox({ width: canvas.clientWidth, height: canvas.clientHeight });
    measure();
    if (typeof ResizeObserver !== 'function') {
      return;
    }
    const observer = new ResizeObserver(measure);
    observer.observe(canvas);
    return () => observer.disconnect();
  }, []);

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
        edgesMeta={graph.meta}
        onPole={onPole}
        onThreshold={setThreshold}
        onLayerFilter={setLayerFilter}
        showGroups={showGroups}
        onShowGroups={setShowGroups}
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
      <div className="field-projection-canvas" ref={canvasRef}>
        <svg
          ref={svgRef}
          className="field-projection-plot"
          viewBox={`${viewBox.x} ${viewBox.y} ${viewBox.width} ${viewBox.height}`}
          role="img"
          aria-label={t('projection.ariaLabel')}
          data-testid="field-projection-plot"
          {...handlers}
          onClick={onClearSelection}
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
            showGroups={showGroups}
            onSelectWell={onSelectWell}
            onHoverWell={holdHover}
          />
        </svg>
        {hover !== null && (
          <div onPointerEnter={keepHover} onPointerLeave={() => holdHover(null)}>
            <NodeTooltip
              hover={hover}
              box={canvasBox}
              row={rowOf(hover.well)}
              step={stepIndex + 1}
            />
          </div>
        )}
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
