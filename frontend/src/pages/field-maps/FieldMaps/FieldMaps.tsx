import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { MapLayerFile, MapsIndexFile } from '@/entities/maps/types';
import { useDataset, useMapLayer } from '@/entities';
import { useI18n } from '@/shared/i18n/I18nContext';
import { useTimeline } from '@/entities/timeline/model/TimelineContext';
import { useTheme } from '@/shared/theme/ThemeContext';
import { ViewStatus } from '@/shared/ui/ViewStatus';
import { rowsAtStep } from '@/entities/wells/model/wellState';
import { MapControls } from '@/pages/field-maps/MapControls/MapControls';
import { MapReadout, type MapHover } from '@/pages/field-maps/MapReadout/MapReadout';
import { MapWellLayer, type WellPlacement } from '@/pages/field-maps/MapWellLayer/MapWellLayer';
import { bhpBounds } from '@/pages/field-maps/MapWellLayer/MapWellLayer';
import { cellAt, layerRange, wellsInLayer } from '@/pages/field-maps/mapModel';
import { useLayerCanvas, useMapPalette } from '@/pages/field-maps/useMapCanvas';
import { gridPointAt, useMapGestures } from '@/pages/field-maps/useMapGestures';
import './FieldMaps.css';

const READOUT_GRACE_MS = 220;

const digitsFor = (scale: string): number =>
  scale === 'categorical' ? 0 : scale === 'log' ? 1 : 3;

const FieldMapsReady = ({ index }: { index: MapsIndexFile }) => {
  const { t, lang } = useI18n();
  const { theme } = useTheme();
  const { timeline, stepIndex, selectedWell, selectWell } = useTimeline();
  const bounds = useMemo(() => layerRange(index), [index]);
  const [propId, setPropId] = useState(index.props[0]?.id ?? 'PORO');
  const [k, setK] = useState(bounds.min);
  const [showWells, setShowWells] = useState(true);
  const [showLabels, setShowLabels] = useState(false);
  const [hover, setHover] = useState<MapHover | null>(null);
  const hoverTimer = useRef<number | null>(null);
  const keepHover = useCallback(() => {
    if (hoverTimer.current !== null) {
      clearTimeout(hoverTimer.current);
      hoverTimer.current = null;
    }
  }, []);
  const releaseHover = useCallback(() => {
    keepHover();
    hoverTimer.current = window.setTimeout(() => setHover(null), READOUT_GRACE_MS);
  }, [keepHover]);
  const [hoveredWell, setHoveredWell] = useState<string | null>(null);
  const canvasRef = useRef<HTMLDivElement>(null);
  const [box, setBox] = useState({ width: 0, height: 0 });

  const prop = index.props.find((item) => item.id === propId) ?? index.props[0];
  const layerState = useMapLayer(prop?.id ?? null, k);
  const layer: MapLayerFile | null = layerState.status === 'ready' ? layerState.data : null;
  const palette = useMapPalette(theme);
  const href = useLayerCanvas(layer, index, prop?.scale ?? 'linear', palette);
  const { svgRef, rectRef, viewBox, scale, handlers, hasDragged } = useMapGestures(
    index.ni,
    index.nj
  );

  const rows = useMemo(
    () => rowsAtStep(timeline.status === 'ready' ? timeline.data : null, stepIndex),
    [timeline, stepIndex]
  );
  const bhp = useMemo(() => bhpBounds(rows), [rows]);
  const placements = useMemo<WellPlacement[]>(
    () =>
      wellsInLayer(index, k).map((well) => ({
        well,
        x: well.i + 0.5,
        y: index.nj - well.j - 0.5
      })),
    [index, k]
  );

  useEffect(() => {
    const node = canvasRef.current;
    if (node === null) {
      return;
    }
    const measure = () => setBox({ width: node.clientWidth, height: node.clientHeight });
    measure();
    if (typeof ResizeObserver !== 'function') {
      return;
    }
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  const onMove = useCallback(
    (event: { clientX: number; clientY: number }) => {
      const rect = svgRef.current?.getBoundingClientRect() ?? rectRef.current;
      if (rect === null || rect.width <= 0 || rect.height <= 0 || layer === null) {
        return;
      }
      const ratioX = (event.clientX - rect.left) / rect.width;
      const ratioY = (event.clientY - rect.top) / rect.height;
      const point = gridPointAt(viewBox, ratioX, ratioY, index.nj);
      const box2 = canvasRef.current?.getBoundingClientRect() ?? rect;
      keepHover();
      setHover({
        x: event.clientX - box2.left,
        y: event.clientY - box2.top,
        cell: cellAt(layer, index, prop?.scale ?? 'linear', point.i, point.j),
        well: hoveredWell
      });
    },
    [svgRef, rectRef, viewBox, index, layer, prop, hoveredWell, keepHover]
  );

  const onSelectWell = useCallback(
    (well: string) => {
      if (!hasDragged()) {
        selectWell(well);
      }
    },
    [hasDragged, selectWell]
  );

  return (
    <section className="field-maps">
      <MapControls
        index={index}
        props={index.props}
        prop={prop}
        layer={layer}
        k={k}
        kMin={bounds.min}
        kMax={bounds.max}
        showWells={showWells}
        showLabels={showLabels}
        onProp={setPropId}
        onLayer={setK}
        onShowWells={setShowWells}
        onShowLabels={setShowLabels}
      />
      <div className="field-maps-canvas" ref={canvasRef}>
        <svg
          ref={svgRef}
          className="field-maps-plot"
          viewBox={`${viewBox.x} ${viewBox.y} ${viewBox.width} ${viewBox.height}`}
          role="img"
          aria-label={t('maps.ariaLabel', { prop: t(`maps.prop.${prop?.id ?? ''}`), k })}
          data-testid="field-maps-plot"
          data-prop={prop?.id}
          data-layer={k}
          {...handlers}
          onPointerMove={(event) => {
            handlers.onPointerMove(event);
            onMove(event);
          }}
          onPointerLeave={() => {
            handlers.onPointerLeave();
            releaseHover();
          }}
          onClick={() => {
            if (!hasDragged()) {
              selectWell(null);
            }
          }}
        >
          {href !== null && (
            <image
              href={href}
              x={0}
              y={0}
              width={index.ni}
              height={index.nj}
              imageRendering="pixelated"
              data-testid="field-maps-heatmap"
            />
          )}
          {showWells && (
            <MapWellLayer
              placements={placements}
              rows={rows}
              bounds={bhp}
              selectedWell={selectedWell}
              showLabels={showLabels}
              scale={scale}
              onSelectWell={onSelectWell}
              onHoverWell={setHoveredWell}
              onFocusWell={onMove}
            />
          )}
        </svg>
        {layerState.status === 'loading' && (
          <p className="field-maps-hint">{t('maps.loading')}</p>
        )}
        {layerState.status === 'error' && (
          <p className="field-maps-hint" data-testid="field-maps-layer-error">
            {t('maps.layerError', { k })}
          </p>
        )}
        {hover !== null && (
          <div onPointerEnter={keepHover} onPointerLeave={releaseHover}>
            <MapReadout
              hover={{ ...hover, well: hoveredWell }}
              box={box}
              propLabel={t(`maps.prop.${prop?.id ?? ''}`)}
              digits={digitsFor(prop?.scale ?? 'linear')}
              layer={k}
              row={hoveredWell === null ? undefined : rows.get(hoveredWell)}
            />
          </div>
        )}
      </div>
      <p className="field-maps-provenance" data-testid="field-maps-provenance">
        {t('maps.provenance', { lang })}
      </p>
    </section>
  );
};

export const FieldMaps = () => {
  const t = useI18n().t;
  const index = useDataset('maps-index');

  if (index.status === 'loading') {
    return <ViewStatus kind="loading" title={t('maps.loading')} />;
  }
  if (index.status === 'error') {
    return <ViewStatus kind="error" title={t('maps.error')} hint={t('maps.errorHint')} />;
  }
  if (index.data.props.length === 0 || index.data.layers.length === 0) {
    return <ViewStatus kind="empty" title={t('maps.empty')} hint={t('maps.emptyHint')} />;
  }
  return <FieldMapsReady index={index.data} />;
};
