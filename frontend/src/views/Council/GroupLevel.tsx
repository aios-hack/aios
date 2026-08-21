import type { HierarchyGroupAllocation } from '../../api/types';
import { useI18n } from '../../i18n/I18nContext';
import { formatNumber } from '../../ui/format';
import { dimState, type CouncilPath, type GroupCard } from './levels';

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
  cards: readonly GroupCard[];
  ungrouped: readonly HierarchyGroupAllocation[];
  showUngrouped: boolean;
  path: CouncilPath | null;
  activeGroup: string | null;
  onSelectGroup: (group: string | null) => void;
  onSelectWell: (well: string) => void;
}

export const GroupLevel = ({
  cards,
  ungrouped,
  showUngrouped,
  path,
  activeGroup,
  onSelectGroup,
  onSelectWell
}: GroupLevelProps) => {
  const { t, lang } = useI18n();

  return (
    <section className="council-level" data-level="groups" data-testid="council-groups">
      <h3 className="council-level-title">{t('council.groups.title')}</h3>
      <div className="council-cards">
        {cards.map((card) => (
          <article
            key={card.group}
            className="council-card"
            data-testid={`council-card-${card.group}`}
            data-state={dimState(path, path?.group === card.group)}
            data-open={activeGroup === card.group}
            style={{ borderTopColor: card.color }}
          >
            <button
              type="button"
              className="council-card-head"
              onClick={() => onSelectGroup(activeGroup === card.group ? null : card.group)}
            >
              <span className="council-card-name">{card.group}</span>
              <span className="council-number" data-testid={`council-received-${card.group}`}>
                {formatNumber(lang, card.received, 1)}
              </span>
            </button>
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
          </article>
        ))}
        {showUngrouped && (
          <article
            className="council-card"
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
      </div>
    </section>
  );
};
