import {
  useCallback,
  useMemo,
  useState,
  type MouseEvent
} from 'react';
import type { TimelineFile } from '@/entities/timeline/types';
import { useHistoryView } from '@/pages/history-matrix/model/HistoryViewContext';
import { dataOf, useDataset } from '@/entities';
import { formatStepDate } from '@/shared/lib/format';
import { readingText } from '@/pages/history-matrix/readings';
import { useI18n, useT } from '@/shared/i18n/I18nContext';
import { useTimeline } from '@/entities/timeline/model/TimelineContext';
import { ratioColor, watercutColor } from '@/shared/theme/scales';
import { useTheme } from '@/shared/theme/ThemeContext';
import {
  legendNotesOf,
  modeSwatchesOf
} from '@/pages/history-matrix/model/chronoLegend';
import { useDeferredClose } from '@/shared/lib/transition/useDeferredClose';
import { ViewStatus } from '@/shared/ui/ViewStatus';
import { devicePixelRatioOf, toCanvasColor } from '@/shared/lib/canvas/canvasColors';
import { useCellKeyboard } from '@/shared/lib/keyboard/useCellKeyboard';
import { indexSteps, lastWatercutByWell, npvByWell, npvCeilingOf } from '@/entities/wells/model/wellFacts';
import { ChronoControls } from '@/pages/history-matrix/ChronoControls/ChronoControls';
import { ChronoTooltip, type HoverTarget } from '@/pages/history-matrix/ChronoTooltip/ChronoTooltip';
import { useChronoPalette } from '@/pages/history-matrix/cells';
import { cellHeightFor, cellWidthFor, geometryOf, hitTest } from '@/pages/history-matrix/geometry';
import { buildRows, groupByWell, sortRows, ungroupedCount } from '@/pages/history-matrix/sortRows';
import { useChronomapCanvas, useCursorCanvas } from '@/pages/history-matrix/useChronomapCanvas';
import { useStageBox } from '@/shared/lib/layout/useStageBox';
import { useReadoutBounds } from '@/pages/history-matrix/model/readoutBounds';
import './Chronomap.css';

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
  const bounds = useReadoutBounds(stage, hover !== null);

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
  const swatches = modeSwatchesOf(metric, t);
  const legendNotes = legendNotesOf({
    metric,
    wells: rows.length,
    steps: data.steps.length,
    ungrouped,
    t
  });

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
              data-guide="history-matrix-axis"
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
