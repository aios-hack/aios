import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent
} from 'react';
import type { TimelineFile } from '../../api/types';
import { useHistoryView } from '../../app/HistoryViewContext';
import { dataOf, useDataset } from '../../data';
import { useT } from '../../i18n/I18nContext';
import { useTimeline } from '../../state/TimelineContext';
import { useTheme } from '../../theme/ThemeContext';
import { wallMarkColors } from '../../theme/tokens';
import type { LegendSwatch } from '../../ui/Legend';
import { ViewStatus } from '../../ui/ViewStatus';
import { toCanvasColor } from '../shared/canvasColors';
import { groupByWell, npvByWell } from '../shared/wellFacts';
import { layoutOf, stepAt, tileIndexAt, tileX } from './layout';
import {
  buildSeries,
  seriesCeiling,
  useWallPalette,
  watercutByWell
} from './series';
import { useWallCanvas, useWallCursor } from './useWallCanvas';
import { WallControls } from './WallControls';
import { buildWallRows, sortWallRows, ungroupedWells } from './wallSort';
import './WallOfLives.css';

const WALL_MARKS = ['line', 'fill', 'shut', 'idle', 'cursor'] as const;

interface WallBox {
  width: number;
  height: number;
}

const useContainerBox = (): [
  (node: HTMLDivElement | null) => void,
  WallBox
] => {
  const [box, setBox] = useState<WallBox>({ width: 0, height: 0 });
  const observer = useRef<ResizeObserver | null>(null);

  useEffect(() => () => observer.current?.disconnect(), []);

  const attach = useCallback((node: HTMLDivElement | null) => {
    observer.current?.disconnect();
    observer.current = null;
    if (node === null) {
      return;
    }
    const measure = (): WallBox => {
      const style = getComputedStyle(node);
      const inset = parseFloat(style.paddingLeft) + parseFloat(style.paddingRight);
      const strip = node.ownerDocument.querySelector('.console-area-timeaxis');
      const floor =
        strip === null ? window.innerHeight : strip.getBoundingClientRect().top;
      const top = node.getBoundingClientRect().top;
      return {
        width: Math.max(0, node.clientWidth - (Number.isFinite(inset) ? inset : 0)),
        height: Math.max(0, floor - top - parseFloat(style.paddingBottom))
      };
    };
    setBox(measure());
    if (typeof ResizeObserver !== 'function') {
      return;
    }
    const next = new ResizeObserver(() => {
      setBox(measure());
    });
    next.observe(node);
    const strip = node.ownerDocument.querySelector('.console-area-timeaxis');
    if (strip !== null) {
      next.observe(strip);
    }
    observer.current = next;
  }, []);

  return [attach, box];
};

const WallReady = ({ data }: { data: TimelineFile }) => {
  const t = useT();
  const { theme } = useTheme();
  const { stepIndex, setStepIndex, selectWell, selectedWell } = useTimeline();
  const npvState = useDataset('npv');
  const graphState = useDataset('graph');
  const { metric, setMetric, sort, setSort } = useHistoryView();
  const [frame, box] = useContainerBox();

  const npv = useMemo(() => npvByWell(dataOf(npvState)), [npvState]);
  const groups = useMemo(() => groupByWell(dataOf(graphState)), [graphState]);
  const series = useMemo(() => buildSeries(data), [data]);
  const ceiling = useMemo(() => seriesCeiling(series), [series]);
  const watercut = useMemo(() => watercutByWell(series), [series]);
  const rows = useMemo(
    () => sortWallRows(buildWallRows(data.wells, groups, npv, watercut), sort),
    [data.wells, groups, npv, watercut, sort]
  );
  const layout = useMemo(
    () => layoutOf(rows.length, box.width, box.height),
    [rows.length, box.width, box.height]
  );
  const palette = useWallPalette(theme);

  const paint = useMemo(
    () => ({ layout, rows, series, ceiling, palette }),
    [layout, rows, series, ceiling, palette]
  );

  const wallSwatches: LegendSwatch[] = WALL_MARKS.map((mark) => ({
    key: mark,
    color: wallMarkColors[mark],
    label: t(`wall.legend.${mark}`)
  }));
  const wallUngrouped = ungroupedWells(rows);
  const wallNotes = [
    {
      text: t('wall.size', { wells: rows.length, steps: data.steps.length }),
      testId: 'wall-legend-size'
    },
    ...(sort === 'watercut' ? [{ text: t('wall.watercutNote') }] : []),
    ...(sort === 'group'
      ? [
          {
            text:
              wallUngrouped.length > 0
                ? t('wall.ungrouped', { wells: wallUngrouped.join(', ') })
                : t('wall.ungroupedNone'),
            testId: 'wall-ungrouped'
          }
        ]
      : []),
    ...(selectedWell !== null
      ? [{ text: t('wall.tile', { well: selectedWell }), testId: 'wall-selected' }]
      : [])
  ];

  const canvasRef = useWallCanvas(paint);
  const cursorRef = useWallCursor(
    layout,
    stepIndex,
    data.steps.length,
    toCanvasColor(palette['--color-accent'])
  );

  const onClick = useCallback(
    (event: MouseEvent<HTMLCanvasElement>) => {
      const { offsetX, offsetY } = event.nativeEvent;
      const index = tileIndexAt(offsetX, offsetY, layout);
      if (index === null) {
        return;
      }
      selectWell(rows[index].well);
      setStepIndex(
        stepAt(offsetX - tileX(index, layout), data.steps.length, layout.tileWidth)
      );
    },
    [layout, rows, selectWell, setStepIndex, data.steps.length]
  );

  return (
    <section className="wall">
      <WallControls
        metric={metric}
        onMetric={setMetric}
        sort={sort}
        onSort={setSort}
        legendSwatches={wallSwatches}
        legendNotes={wallNotes}
      />
      <div className="wall-body">
        <div className="wall-frame" ref={frame}>
          <div
            className="wall-stage"
            style={{ width: `${layout.width}px`, height: `${layout.height}px` }}
          >
            <canvas
              ref={canvasRef}
              className="wall-canvas"
              data-tiles={rows.length}
              data-columns={layout.columns}
              data-sort={sort}
              data-wells={rows.map((row) => row.well).join(' ')}
              aria-label={t('wall.ariaLabel')}
              role="img"
              onClick={onClick}
            />
            <canvas
              ref={cursorRef}
              className="wall-cursor"
              data-step={stepIndex}
              aria-hidden="true"
            />
          </div>
        </div>
      </div>
    </section>
  );
};

export const WallOfLives = () => {
  const t = useT();
  const { timeline } = useTimeline();

  if (timeline.status === 'loading') {
    return <ViewStatus kind="loading" title={t('wall.loading')} />;
  }
  if (timeline.status === 'error') {
    return <ViewStatus kind="error" title={t('wall.error')} hint={t('wall.errorHint')} />;
  }
  if (timeline.data.steps.length === 0 || timeline.data.wells.length === 0) {
    return <ViewStatus kind="empty" title={t('wall.empty')} hint={t('wall.emptyHint')} />;
  }

  return <WallReady data={timeline.data} />;
};
