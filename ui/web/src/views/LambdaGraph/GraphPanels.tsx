import type { GraphFile } from '../../api/types';
import { useT } from '../../i18n/I18nContext';
import { groupColor } from '../../theme/tokens';
import { formatWindowDate, groupIndex, roundWeight, type Selection } from './model';

export const WindowBadge = ({ window }: { window: GraphFile['window'] }) => {
  const t = useT();
  return (
    <div className="lambda-graph-window" data-testid="lambda-graph-window">
      <strong className="lambda-graph-window-badge">
        {t('graph.window.badge', {
          start: formatWindowDate(window.start),
          end: formatWindowDate(window.end)
        })}
      </strong>
      <span className="lambda-graph-window-note">{t('graph.window.note')}</span>
    </div>
  );
};

interface ThresholdControlProps {
  value: number;
  min: number;
  max: number;
  shown: number;
  total: number;
  onChange: (value: number) => void;
}

export const ThresholdControl = ({
  value,
  min,
  max,
  shown,
  total,
  onChange
}: ThresholdControlProps) => {
  const t = useT();
  const step = Math.max((max - min) / 100, 0.001);
  return (
    <div className="lambda-graph-threshold">
      <label className="lambda-graph-threshold-label" htmlFor="lambda-threshold">
        {t('graph.threshold.label')}
      </label>
      <input
        id="lambda-threshold"
        className="lambda-graph-slider"
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
      />
      <output className="lambda-graph-threshold-value">{roundWeight(value)}</output>
      <span className="lambda-graph-count" data-testid="lambda-graph-count">
        {t('graph.threshold.edges', { shown, total })}
      </span>
    </div>
  );
};

export const GroupLegend = ({ data }: { data: GraphFile }) => {
  const t = useT();
  const index = groupIndex(data);
  return (
    <div className="lambda-graph-legend">
      <span className="lambda-graph-legend-title">{t('graph.legend.title')}</span>
      <ul className="lambda-graph-legend-list">
        {data.groups.map((group) => (
          <li key={group.id} className="lambda-graph-legend-item">
            <span
              className="lambda-graph-swatch"
              style={{ background: groupColor(index.get(group.id) ?? 0) }}
            />
            {group.id}
          </li>
        ))}
      </ul>
      <ul className="lambda-graph-legend-list">
        <li className="lambda-graph-legend-item">
          <span className="lambda-graph-shape lambda-graph-shape-inj" />
          {t('graph.legend.injector')}
        </li>
        <li className="lambda-graph-legend-item">
          <span className="lambda-graph-shape lambda-graph-shape-prod" />
          {t('graph.legend.producer')}
        </li>
      </ul>
    </div>
  );
};

export const MetaPanel = ({ meta }: { meta: GraphFile['meta'] }) => {
  const t = useT();
  const rows: [string, string][] = [
    ['graph.meta.lag', t('graph.meta.lagValue', { value: meta.lag_months })],
    ['graph.meta.amplitude', meta.amplitude.toFixed(2)],
    ['graph.meta.stability', meta.stability.toFixed(2)],
    ['graph.meta.rank', String(meta.rank)],
    ['graph.meta.condition', meta.condition_number.toFixed(2)]
  ];
  return (
    <section className="lambda-graph-meta">
      <h3 className="lambda-graph-meta-title">{t('graph.meta.title')}</h3>
      <dl className="lambda-graph-meta-list">
        {rows.map(([key, value]) => (
          <div key={key} className="lambda-graph-meta-row">
            <dt className="lambda-graph-meta-key">{t(key)}</dt>
            <dd className="lambda-graph-meta-value">{value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
};

interface SelectionPanelProps {
  selection: Selection;
  onClear: () => void;
}

export const SelectionPanel = ({ selection, onClear }: SelectionPanelProps) => {
  const t = useT();
  const count = selection.neighbours.size;
  return (
    <section className="lambda-graph-selection" data-testid="lambda-graph-selection">
      <h3 className="lambda-graph-selection-title">
        {t('graph.selection.title', { well: selection.well })}
      </h3>
      {selection.group !== null && (
        <p className="lambda-graph-selection-row">
          {t('graph.selection.group', { group: selection.group })}
        </p>
      )}
      <p className="lambda-graph-selection-row">
        {count > 0
          ? t('graph.selection.neighbours', { count })
          : t('graph.selection.none')}
      </p>
      <button type="button" className="lambda-graph-clear" onClick={onClear}>
        {t('graph.selection.clear')}
      </button>
    </section>
  );
};
