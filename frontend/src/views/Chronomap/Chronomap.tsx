import { useCallback, useMemo, useState, type MouseEvent } from 'react';
import type { TimelineFile } from '../../api/types';
import { useHistoryView } from '../../app/HistoryViewContext';
import { dataOf, useDataset } from '../../data';
import { useT } from '../../i18n/I18nContext';
import { useTimeline } from '../../state/TimelineContext';
import { ratioColor, watercutColor } from '../../theme/scales';
import { useTheme } from '../../theme/ThemeContext';
import { chronoModeColors } from '../../theme/tokens';
import type { LegendSwatch } from '../../ui/Legend';
import { ViewStatus } from '../../ui/ViewStatus';
import { toCanvasColor } from '../shared/canvasColors';
import { useCellKeyboard } from '../shared/useCellKeyboard';
import { indexSteps, lastWatercutByWell, npvByWell, npvCeilingOf } from '../shared/wellFacts';
import { ChronoControls } from './ChronoControls';
import { ChronoTooltip, type HoverTarget } from './ChronoTooltip';
import { useChronoPalette } from './cells';
import { geometryOf, hitTest } from './geometry';
import { buildRows, groupByWell, sortRows, ungroupedCount } from './sortRows';
import { useChronomapCanvas, useCursorCanvas } from './useChronomapCanvas';
import './Chronomap.css';

const CHRONO_MODES = ['production', 'injection', 'shut', 'idle'] as const;

const ChronomapReady = ({ data }: { data: TimelineFile }) => {
  const t = useT();
  const { theme } = useTheme();
  const { stepIndex, setStepIndex, selectWell } = useTimeline();
  const npvState = useDataset('npv');
  const graphState = useDataset('graph');
  const { metric, setMetric, sort, setSort } = useHistoryView();
  const [hover, setHover] = useState<HoverTarget | null>(null);

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
    () => geometryOf(data.steps.length, rows.length),
    [data.steps.length, rows.length]
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
      surfaceColor: toCanvasColor(palette['--color-plot-bg'])
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

  const canvasRef = useChronomapCanvas(paint);
  const cursorRef = useCursorCanvas(
    geometry,
    stepIndex,
    toCanvasColor(palette['--scale-watercut-1'])
  );

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
        <div
          className="chronomap-stage"
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
          {hover !== null && (
            <ChronoTooltip
              target={hover}
              step={data.steps[hover.column]}
              row={index[hover.column]?.get(hover.well)}
              metric={metric}
              npv={npv.get(hover.well)}
            />
          )}
        </div>
        <p className="chronomap-announce" aria-live="polite" data-testid="chronomap-announce">
          {cursorWell === null || cursorStep === undefined
            ? ''
            : t('chrono.cellAnnounce', {
                well: cursorWell,
                date: cursorStep.date,
                value:
                  cursorRow === undefined
                    ? t('chrono.notMeasured')
                    : String(
                        metric === 'watercut'
                          ? cursorRow.watercut
                          : metric === 'ratio'
                            ? cursorRow.fact_to_target
                            : cursorRow.operating_status
                      )
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
