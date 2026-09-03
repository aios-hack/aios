import type { CSSProperties } from 'react';
import type { HierarchyGroupAllocation, HierarchyStep } from '../../api/types';
import { useI18n } from '../../i18n/I18nContext';
import { DASH, formatNumber, formatPercent } from '../../ui/format';
import { dimState, type CouncilPath, type FieldSegment, type GroupCard } from './levels';

const INLINE_SHARE = 0.08;

interface AllocationListProps {
  items: readonly HierarchyGroupAllocation[];
  selected: string | null;
  onSelectWell: (well: string) => void;
}

const AllocationList = ({ items, selected, onSelectWell }: AllocationListProps) => {
  const { lang } = useI18n();
  return (
    <ul className="council-alloc">
      {items.map((item) => (
        <li key={item.well} className="council-alloc-row" data-active={item.well === selected}>
          <button
            type="button"
            className="council-alloc-well"
            data-testid={`council-alloc-${item.well}`}
            onClick={() => onSelectWell(item.well)}
          >
            {item.well}
          </button>
          <span className="council-number">{formatNumber(lang, item.value_m3_per_day, 1)}</span>
        </li>
      ))}
    </ul>
  );
};

interface GroupLevelProps {
  step: HierarchyStep;
  segments: readonly FieldSegment[];
  cards: readonly GroupCard[];
  ungrouped: readonly HierarchyGroupAllocation[];
  showUngrouped: boolean;
  path: CouncilPath | null;
  activeGroup: string | null;
  onSelectGroup: (group: string | null) => void;
  onSelectWell: (well: string) => void;
}

export const GroupLevel = ({
  step,
  segments,
  cards,
  ungrouped,
  showUngrouped,
  path,
  activeGroup,
  onSelectGroup,
  onSelectWell
}: GroupLevelProps) => {
  const { t, lang } = useI18n();
  const limit = step.field.injection_limit_m3_per_day;
  const available = step.field.water_available_m3_per_day;
  const usage = available > 0 ? limit / available : null;

  return (
    <section
      className="council-level"
      data-level="groups"
      data-testid="council-groups"
      data-guide="council-groups"
    >
      <header className="council-level-head">
        <h3 className="council-level-title">{t('council.groups.title')}</h3>
      </header>
      <div className="council-groups" role="list" aria-label={t('council.field.barLabel')}>
        {cards.map((card, index) => {
          const segment = segments.find((item) => item.group === card.group) ?? null;
          const share = segment?.share ?? null;
          const weight = share === null ? 1 / cards.length : share;
          const idle = card.received === 0;
          return (
            <div
              key={card.group}
              role="listitem"
              className="council-column tile-enter"
              data-testid={`council-segment-${card.group}`}
              style={{ flexGrow: Math.max(weight, 0), '--tile-index': index } as CSSProperties}
              data-empty={idle ? 'true' : undefined}
              data-inline={weight >= INLINE_SHARE}
              data-state={dimState(path, path?.group === card.group)}
              data-open={activeGroup === card.group}
              title={`${card.group} · ${segment === null ? DASH : formatNumber(lang, segment.limit, 1)}`}
            >
              <button
                type="button"
                className="council-column-pick"
                aria-label={card.group}
                aria-pressed={activeGroup === card.group}
                onClick={() => onSelectGroup(activeGroup === card.group ? null : card.group)}
              />
              <span className="council-cap" style={{ background: segment?.color }}>
                <span className="council-cap-name">{card.group}</span>
                <span className="council-cap-share council-number">
                  {share === null ? DASH : formatPercent(lang, share)}
                </span>
              </span>
              <div
                className="council-card"
                data-testid={`council-card-${card.group}`}
                data-state={dimState(path, path?.group === card.group)}
                data-open={activeGroup === card.group}
                data-empty={idle ? 'true' : undefined}
                style={{ '--council-card-accent': card.color } as CSSProperties}
              >
                <span className="council-card-total">
                  {idle ? null : (
                    <span className="council-card-total-label">
                      {t('council.groups.received')}
                    </span>
                  )}
                  <span
                    className="council-number"
                    data-testid={`council-received-${card.group}`}
                  >
                    {formatNumber(lang, card.received, 1)}
                  </span>
                </span>
                {idle ? null : (
                  <>
                    <span className="council-card-listlabel">
                      {t('council.groups.wells')}
                    </span>
                    <AllocationList
                      items={card.top}
                      selected={path?.well ?? null}
                      onSelectWell={onSelectWell}
                    />
                    {card.rest > 0 && (
                      <p className="council-card-rest">
                        {t('council.groups.rest', {
                          count: card.rest,
                          value: formatNumber(lang, card.restTotal, 1)
                        })}
                      </p>
                    )}
                  </>
                )}
              </div>
            </div>
          );
        })}
      </div>
      <footer className="council-budget">
        <div className="council-budget-stat">
          <span className="council-budget-label">{t('council.field.budget')}</span>
          <span className="council-number council-budget-value" data-testid="council-field-limit">
            {formatNumber(lang, limit, 1)}
            <span className="council-budget-unit">{t('council.field.unit')}</span>
          </span>
        </div>
        <div className="council-budget-stat">
          <span className="council-budget-label">{t('council.field.outOf')}</span>
          <span
            className="council-number council-budget-value"
            data-testid="council-field-available"
          >
            {formatNumber(lang, available, 1)}
            <span className="council-budget-unit">{t('council.field.unit')}</span>
          </span>
        </div>
        <div className="council-budget-stat council-budget-stat-usage">
          <span className="council-budget-label">{t('council.field.usage')}</span>
          <span className="council-budget-gauge">
            <span
              className="council-budget-meter"
              aria-hidden="true"
              data-unknown={usage === null ? 'true' : undefined}
            >
              {usage !== null && (
                <span
                  className="council-budget-meter-fill"
                  style={{ inlineSize: `${Math.min(usage, 1) * 100}%` }}
                />
              )}
            </span>
            <span className="council-number council-budget-usage">
              {usage === null ? DASH : formatPercent(lang, usage)}
            </span>
          </span>
        </div>
      </footer>
      {showUngrouped && (
        <article
          className="council-card council-card-loose"
          data-ungrouped="true"
          data-testid="council-card-ungrouped"
          data-state={dimState(path, path?.group === null)}
          data-open={activeGroup === null && path?.group === null}
        >
          <button
            type="button"
            className="council-card-head"
            onClick={() => onSelectGroup(null)}
          >
            <span className="council-card-name">{t('council.groups.ungrouped')}</span>
            <span className="council-number">{ungrouped.length}</span>
          </button>
          <p className="council-card-rest">{t('council.groups.ungroupedNote')}</p>
          <AllocationList
            items={ungrouped}
            selected={path?.well ?? null}
            onSelectWell={onSelectWell}
          />
        </article>
      )}
    </section>
  );
};
