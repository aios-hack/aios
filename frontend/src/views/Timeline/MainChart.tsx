import { memo, useCallback, useMemo, useRef } from 'react';
import type { TimelineStep } from '../../api/types';
import { useI18n } from '../../i18n/I18nContext';
import { formatNumber, formatStepDate } from '../../ui/format';
import { indexFromRatio, panelGeometry, yearTicks } from './chartGeometry';
import './MainChart.css';

interface MainChartProps {
  steps: TimelineStep[];
  stepIndex: number;
  onSelect: (index: number) => void;
}

const PLOT_WIDTH = 100;
const PANEL_HEIGHT = 26;
const PANEL_GAP = 12;
const TOP_PAD = 2;
const TOTAL_HEIGHT = TOP_PAD * 2 + PANEL_HEIGHT * 2 + PANEL_GAP;
const UPPER_TOP = TOP_PAD;
const LOWER_TOP = TOP_PAD + PANEL_HEIGHT + PANEL_GAP;
const MAX_YEAR_LABELS = 10;

const MainChartView = ({ steps, stepIndex, onSelect }: MainChartProps) => {
  const { t, lang } = useI18n();
  const svgRef = useRef<SVGSVGElement | null>(null);
  const total = steps.length;

  const upper = useMemo(
    () =>
      panelGeometry(
        steps.map((step) => step.field.npv_cumulative),
        { width: PLOT_WIDTH, top: UPPER_TOP, height: PANEL_HEIGHT, total }
      ),
    [steps, total]
  );
  const lower = useMemo(
    () =>
      panelGeometry(
        steps.map((step) => step.field.production),
        { width: PLOT_WIDTH, top: LOWER_TOP, height: PANEL_HEIGHT, total }
      ),
    [steps, total]
  );
  const ticks = useMemo(
    () =>
      yearTicks(steps.map((step) => step.date), {
        width: PLOT_WIDTH,
        total,
        maxLabels: MAX_YEAR_LABELS
      }),
    [steps, total]
  );

  const cursorX = (stepIndex / Math.max(total - 1, 1)) * PLOT_WIDTH;

  const pick = useCallback(
    (clientX: number) => {
      const svg = svgRef.current;
      if (svg === null) {
        return;
      }
      const box = svg.getBoundingClientRect();
      if (box.width <= 0) {
        return;
      }
      onSelect(indexFromRatio((clientX - box.left) / box.width, total));
    },
    [onSelect, total]
  );

  const panels = [
    {
      key: 'npv',
      geometry: upper,
      label: t('steps.chart.npv'),
      stroke: 'var(--color-accent)'
    },
    {
      key: 'production',
      geometry: lower,
      label: t('steps.chart.production'),
      stroke: 'var(--color-oil)'
    }
  ];

  return (
    <figure className="timeline-chart">
      <figcaption className="timeline-chart-caption">{t('steps.chart.title')}</figcaption>
      <svg
        ref={svgRef}
        className="timeline-chart-svg"
        viewBox={`0 0 ${PLOT_WIDTH} ${TOTAL_HEIGHT}`}
        preserveAspectRatio="none"
        role="img"
        aria-label={t('steps.chart.title')}
        data-cursor-step={stepIndex}
        onPointerDown={(event) => {
          event.currentTarget.setPointerCapture(event.pointerId);
          pick(event.clientX);
        }}
        onPointerMove={(event) => {
          if (event.buttons === 1) {
            pick(event.clientX);
          }
        }}
      >
        {panels.map((panel) => (
          <g key={panel.key} data-panel={panel.key}>
            <rect
              className="timeline-chart-plot"
              x={0}
              y={panel.geometry.top}
              width={PLOT_WIDTH}
              height={PANEL_HEIGHT}
            />
            {panel.geometry.segments.map((segment) => (
              <polyline
                key={segment.slice(0, 24)}
                className="timeline-chart-line"
                points={segment}
                stroke={panel.stroke}
                vectorEffect="non-scaling-stroke"
              />
            ))}
          </g>
        ))}
        {ticks.map((tick) => (
          <line
            key={tick.year}
            className="timeline-chart-grid"
            x1={tick.x}
            x2={tick.x}
            y1={UPPER_TOP}
            y2={LOWER_TOP + PANEL_HEIGHT}
            vectorEffect="non-scaling-stroke"
          />
        ))}
        <line
          className="timeline-chart-cursor"
          data-testid="chart-cursor"
          x1={cursorX}
          x2={cursorX}
          y1={UPPER_TOP}
          y2={LOWER_TOP + PANEL_HEIGHT}
          vectorEffect="non-scaling-stroke"
        />
      </svg>
      <div className="timeline-chart-axis-x">
        {ticks.map((tick) => (
          <span
            className="timeline-chart-tick"
            key={tick.year}
            style={{ left: `${tick.x}%` }}
          >
            {tick.year}
          </span>
        ))}
      </div>
      <div className="timeline-chart-legend">
        {panels.map((panel) => (
          <p className="timeline-chart-axis" key={panel.key} data-axis={panel.key}>
            <span className="timeline-chart-axis-label">{panel.label}</span>
            <span className="timeline-chart-axis-range">
              {formatNumber(lang, panel.geometry.min)} … {formatNumber(lang, panel.geometry.max)}
            </span>
          </p>
        ))}
      </div>
      <p className="timeline-chart-cursor-label">
        {formatStepDate(lang, steps[stepIndex].date)}
      </p>
    </figure>
  );
};

export const MainChart = memo(MainChartView);
