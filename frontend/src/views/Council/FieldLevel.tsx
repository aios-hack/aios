import type { HierarchyStep } from '../../api/types';
import { useI18n } from '../../i18n/I18nContext';
import { formatNumber, formatPercent } from '../../ui/format';
import { dimState, type CouncilPath, type FieldSegment } from './levels';

interface FieldLevelProps {
  step: HierarchyStep;
  segments: readonly FieldSegment[];
  path: CouncilPath | null;
  onSelectGroup: (group: string) => void;
}

export const FieldLevel = ({ step, segments, path, onSelectGroup }: FieldLevelProps) => {
  const { t, lang } = useI18n();

  return (
    <section className="council-level" data-level="field" data-testid="council-field">
      <header className="council-level-head">
        <h3 className="council-level-title">{t('council.field.title')}</h3>
        <dl className="council-field-stats">
          <div className="council-stat">
            <dt>{t('council.field.limit')}</dt>
            <dd className="council-number" data-testid="council-field-limit">
              {formatNumber(lang, step.field.injection_limit_m3_per_day, 1)}
            </dd>
          </div>
          <div className="council-stat">
            <dt>{t('council.field.available')}</dt>
            <dd className="council-number" data-testid="council-field-available">
              {formatNumber(lang, step.field.water_available_m3_per_day, 1)}
            </dd>
          </div>
        </dl>
      </header>
      <div className="council-bar" role="list" aria-label={t('council.field.barLabel')}>
        {segments.map((segment) => (
          <button
            key={segment.group}
            type="button"
            role="listitem"
            className="council-bar-segment"
            data-testid={`council-segment-${segment.group}`}
            data-state={dimState(path, path?.group === segment.group)}
            data-empty={segment.share === 0}
            style={{
              flexGrow: segment.share,
              background: segment.color
            }}
            title={`${segment.group} · ${formatNumber(lang, segment.limit, 1)}`}
            onClick={() => onSelectGroup(segment.group)}
          >
            <span className="council-bar-label">{segment.group}</span>
          </button>
        ))}
      </div>
      <ul className="council-legend">
        {segments.map((segment) => (
          <li
            key={segment.group}
            className="council-legend-item"
            data-state={dimState(path, path?.group === segment.group)}
          >
            <span className="council-swatch" style={{ background: segment.color }} />
            <span className="council-legend-name">{segment.group}</span>
            <span className="council-number">{formatNumber(lang, segment.limit, 1)}</span>
            <span className="council-number council-muted">
              {formatPercent(lang, segment.share)}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
};
