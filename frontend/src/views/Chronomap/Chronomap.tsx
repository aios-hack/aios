import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent
} from 'react';
import type { TimelineFile } from '../../api/types';
import { useHistoryView } from '../../app/HistoryViewContext';
import { dataOf, useDataset } from '../../data';
import { formatStepDate } from '../../ui/format';
import { readingText } from './readings';
import { useI18n, useT } from '../../i18n/I18nContext';
import { useTimeline } from '../../state/TimelineContext';
import { ratioColor, watercutColor } from '../../theme/scales';
import { useTheme } from '../../theme/ThemeContext';
import { chronoModeColors } from '../../theme/tokens';
import type { LegendSwatch } from '../../ui/Legend';
import { useDeferredClose } from '../../ui/Inspector/useDeferredClose';
import { ViewStatus } from '../../ui/ViewStatus';
import { devicePixelRatioOf, toCanvasColor } from '../shared/canvasColors';
import { useCellKeyboard } from '../shared/useCellKeyboard';
import { indexSteps, lastWatercutByWell, npvByWell, npvCeilingOf } from '../shared/wellFacts';
import { ChronoControls } from './ChronoControls';
import { ChronoTooltip, type HoverTarget, type ReadoutBounds } from './ChronoTooltip';
import { useChronoPalette } from './cells';
import { cellHeightFor, cellWidthFor, geometryOf, hitTest } from './geometry';
import { buildRows, groupByWell, sortRows, ungroupedCount } from './sortRows';
import { useChronomapCanvas, useCursorCanvas } from './useChronomapCanvas';
import './Chronomap.css';

const CHRONO_MODES = ['production', 'injection', 'shut', 'idle'] as const;

interface StageBox {
  width: number;
  height: number;
}

const useStageBox = (): [(node: HTMLDivElement | null) => void, StageBox] => {
  const [box, setBox] = useState<StageBox>({ width: 0, height: 0 });
  const observer = useRef<ResizeObserver | null>(null);

  useEffect(() => () => observer.current?.disconnect(), []);

  const attach = useCallback((node: HTMLDivElement | null) => {
    observer.current?.disconnect();
    observer.current = null;
    if (node === null) {
      return;
    }
    const measure = (): StageBox => ({
      width: node.clientWidth,
      height: node.clientHeight
    });
    setBox(measure());
    if (typeof ResizeObserver !== 'function') {
      return;
    }
    const next = new ResizeObserver(() => {
      setBox(measure());
    });
    next.observe(node);
    observer.current = next;
  }, []);

  return [attach, box];
};

export const OBSTRUCTION_SELECTORS = [
  '.time-scale-backdrop path',
  '.time-scale-backdrop',
  '.console-area-timeaxis'
];

export interface ViewportBox {
  width: number;
  height: number;
}

export const readoutBoundsOf = (
  stage: DOMRect,
  viewport: ViewportBox,
  clips: DOMRect[],
  obstruction: DOMRect | null
): ReadoutBounds => {
  let left = 0;
  let right = viewport.width;
  let top = 0;
  let bottom = viewport.height;
  for (const clip of clips) {
    left = Math.max(left, clip.left);
    right = Math.min(right, clip.right);
    top = Math.max(top, clip.top);
    bottom = Math.min(bottom, clip.bottom);
  }
  if (obstruction !== null && obstruction.top < bottom && obstruction.bottom > top) {
    bottom = Math.min(bottom, obstruction.top);
  }
  return {
    left: left - stage.left,
    right: right - stage.left,
    top: top - stage.top,
    bottom: Math.max(top - stage.top, bottom - stage.top)
  };
};

const obstructionRect = (stage: HTMLElement): DOMRect | null => {
  const doc = stage.ownerDocument;
  for (const selector of OBSTRUCTION_SELECTORS) {
    const node = doc.querySelector(selector);
    if (node === null) {
      continue;
    }
    const rect = node.getBoundingClientRect();
    if (rect.height > 0) {
      return rect;
    }
  }
  return null;
};

const clipRectsOf = (stage: HTMLElement): DOMRect[] => {
  const clips: DOMRect[] = [];
  let node = stage.parentElement;
  while (node !== null && node !== stage.ownerDocument.body) {
    const style = getComputedStyle(node);
    if (/auto|scroll|hidden|clip/.test(`${style.overflowX}${style.overflowY}`)) {
      clips.push(node.getBoundingClientRect());
    }
    node = node.parentElement;
  }
  return clips;
};

const sameBounds = (a: ReadoutBounds, b: ReadoutBounds): boolean =>
  a.left === b.left && a.right === b.right && a.top === b.top && a.bottom === b.bottom;

const useReadoutBounds = (
  stage: HTMLDivElement | null,
  hover: HoverTarget | null
): ReadoutBounds => {
  const [bounds, setBounds] = useState<ReadoutBounds>({
    left: 0,
    right: Number.POSITIVE_INFINITY,
    top: 0,
    bottom: Number.POSITIVE_INFINITY
  });

  useLayoutEffect(() => {
    if (stage === null) {
      return;
    }
    const measure = () => {
      const next = readoutBoundsOf(
        stage.getBoundingClientRect(),
        { width: window.innerWidth, height: window.innerHeight },
        clipRectsOf(stage),
        obstructionRect(stage)
      );
      setBounds((prev) => (sameBounds(prev, next) ? prev : next));
    };
    measure();
    const strip = stage.ownerDocument.querySelector('.time-scale');
    window.addEventListener('resize', measure);
    window.addEventListener('scroll', measure, true);
    strip?.addEventListener('transitionrun', measure);
    strip?.addEventListener('transitionend', measure);
    return () => {
      window.removeEventListener('resize', measure);
      window.removeEventListener('scroll', measure, true);
      strip?.removeEventListener('transitionrun', measure);
      strip?.removeEventListener('transitionend', measure);
    };
  }, [stage, hover]);

  return bounds;
};

const ChronomapReady = ({ data }: { data: TimelineFile }) => {
  const { t, lang } = useI18n();
  const { theme } = useTheme();
  const { stepIndex, setStepIndex, selectWell } = useTimeline();
  const npvState = useDataset('npv');
  const graphState = useDataset('graph');
  const { metric, setMetric, sort, setSort } = useHistoryView();
  const [hover, setHover] = useState<HoverTarget | null>(null);
  const [frame, frameBox] = useStageBox();
  const [stage, setStage] = useState<HTMLDivElement | null>(null);
  const bounds = useReadoutBounds(stage, hover);

  const npv = useMemo(() => npvByWell(dataOf(npvState)), [npvState]);
  const npvCeiling = useMemo(() => npvCeilingOf(npv), [npv]);
  const groups = useMemo(() => groupByWell(dataOf(graphState)), [graphState]);
  const watercut = useMemo(() => lastWatercutByWell(data), [data]);
  const rows = useMemo(
    () => sortRows(buildRows(data.wells, groups, npv, watercut), sort),
    [data.wells, groups, npv, watercut, sort]
  );
  const index = useMemo(() => indexSteps(data), [data]);
  const geometry = useMemo(
    () =>
      geometryOf(
        data.steps.length,
        rows.length,
        cellWidthFor(data.steps.length, frameBox.width, devicePixelRatioOf()),
        cellHeightFor(rows.length, frameBox.height, devicePixelRatioOf())
      ),
    [data.steps.length, rows.length, frameBox.width, frameBox.height]
  );

  const palette = useChronoPalette(theme);

  const paint = useMemo(
    () => ({
      geometry,
      rows,
      steps: data.steps,
      index,
      context: { metric, palette, npv, npvCeiling },
      axisColor: toCanvasColor(palette['--color-axis-tick']),
      surfaceColor: toCanvasColor(palette['--color-plot-grid'])
    }),
    [geometry, rows, data.steps, index, metric, palette, npv, npvCeiling]
  );

  const ungrouped = ungroupedCount(rows);
  const swatches: LegendSwatch[] | undefined =
    metric === 'mode'
      ? CHRONO_MODES.map((mode) => ({
          key: mode,
          color: chronoModeColors[mode],
          label: t(`chrono.mode.${mode}`)
        }))
      : undefined;
  const legendNotes = [
    {
      text: t('chrono.size', { wells: rows.length, steps: data.steps.length }),
      testId: 'chrono-legend-size'
    },
    { text: t('chrono.legend.terminal') },
    ...(metric === 'npv' ? [{ text: t('chrono.npvNote') }] : []),
    {
      text:
        ungrouped > 0
          ? t('chrono.ungrouped', { count: ungrouped })
          : t('chrono.ungroupedNone')
    }
  ];

  const { visible: readout, closing: readoutClosing } = useDeferredClose(hover);

  const canvasRef = useChronomapCanvas(paint);
  const cursorRef = useCursorCanvas(geometry, stepIndex, {
    ink: toCanvasColor(palette['--color-cursor-ink']),
    halo: toCanvasColor(palette['--color-cursor-halo'])
  });

  const onMove = useCallback(
    (event: MouseEvent<HTMLCanvasElement>) => {
      const hit = hitTest(event.nativeEvent.offsetX, event.nativeEvent.offsetY, geometry);
      if (hit === null) {
        setHover(null);
        return;
      }
      setHover({
        well: rows[hit.row].well,
        column: hit.column,
        x: event.nativeEvent.offsetX,
        y: event.nativeEvent.offsetY
      });
    },
    [geometry, rows]
  );

  const commitCell = useCallback(
    ({ row, column }: { row: number; column: number }) => {
      const target = rows[row];
      if (target === undefined) {
        return;
      }
      selectWell(target.well);
      setStepIndex(column);
    },
    [rows, selectWell, setStepIndex]
  );

  const { cursor, onKeyDown } = useCellKeyboard({
    rowCount: rows.length,
    columnCount: geometry.columns,
    onCommit: commitCell
  });

  const cursorWell = rows[cursor.row]?.well ?? null;
  const cursorStep = data.steps[cursor.column];
  const cursorRow = index[cursor.column]?.get(cursorWell ?? '');

  const onClick = useCallback(
    (event: MouseEvent<HTMLCanvasElement>) => {
      const hit = hitTest(event.nativeEvent.offsetX, event.nativeEvent.offsetY, geometry);
      if (hit === null) {
        return;
      }
      selectWell(rows[hit.row].well);
      setStepIndex(hit.column);
    },
    [geometry, rows, selectWell, setStepIndex]
  );

  return (
    <section className="chronomap">
      <ChronoControls
        metric={metric}
        sort={sort}
        onMetric={setMetric}
        onSort={setSort}
        legendSwatches={swatches}
        legendRamp={
          metric === 'mode'
            ? undefined
            : {
                colorAt: metric === 'watercut' ? watercutColor : ratioColor,
                lowLabel: t(`chrono.legend.low.${metric}`),
                highLabel: t(`chrono.legend.high.${metric}`)
              }
        }
        legendNotes={legendNotes}
      />
      <div className="chronomap-body">
        <div className="chronomap-frame" ref={frame}>
          <div
            className="chronomap-stage"
            ref={setStage}
            style={{ width: `${geometry.width}px`, height: `${geometry.height}px` }}
            onMouseLeave={() => setHover(null)}
          >
            <canvas
              ref={canvasRef}
              className="chronomap-canvas"
              data-columns={geometry.columns}
              data-rows={geometry.rows}
              aria-label={t('chrono.ariaLabel')}
              role="img"
              tabIndex={0}
              data-cursor-row={cursor.row}
              data-cursor-column={cursor.column}
              onMouseMove={onMove}
              onClick={onClick}
              onKeyDown={onKeyDown}
            />
            <canvas
              ref={cursorRef}
              className="chronomap-cursor"
              data-step={stepIndex}
              aria-hidden="true"
            />
            {readout !== null && (
              <ChronoTooltip
                bounds={bounds}
                target={readout}
                step={data.steps[readout.column]}
                row={index[readout.column]?.get(readout.well)}
                metric={metric}
                npv={npv.get(readout.well)}
                group={groups.get(readout.well) ?? null}
                closing={readoutClosing}
              />
            )}
          </div>
        </div>
        <p className="chronomap-announce" aria-live="polite" data-testid="chronomap-announce">
          {cursorWell === null || cursorStep === undefined
            ? ''
            : t('chrono.cellAnnounce', {
                well: cursorWell,
                date: formatStepDate(lang, cursorStep.date),
                value: readingText({ lang, t, metric, row: cursorRow })
              })}
        </p>
      </div>
    </section>
  );
};

export const Chronomap = () => {
  const t = useT();
  const { timeline } = useTimeline();

  if (timeline.status === 'loading') {
    return <ViewStatus kind="loading" title={t('chrono.loading')} />;
  }
  if (timeline.status === 'error') {
    return (
      <ViewStatus kind="error" title={t('chrono.error')} hint={t('chrono.errorHint')} />
    );
  }
  if (timeline.data.steps.length === 0 || timeline.data.wells.length === 0) {
    return <ViewStatus kind="empty" title={t('chrono.empty')} hint={t('chrono.emptyHint')} />;
  }

  return <ChronomapReady data={timeline.data} />;
};
