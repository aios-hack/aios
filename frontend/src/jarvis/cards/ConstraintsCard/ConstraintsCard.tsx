import { DASH, formatNumber } from '@/shared/lib/format';
import { useI18n } from '@/shared/i18n/I18nContext';
import type { Lang } from '@/shared/i18n/dictionaries';
import { readConstraints } from '@/jarvis/cards/payloads';
import { EmptyPayload } from '@/jarvis/cards/EmptyPayload/EmptyPayload';
import type { ConstraintRow } from '@/jarvis/cards/payloads/payloadTypes';
import './ConstraintsCard.css';

const cellOf = (lang: Lang, row: ConstraintRow): string => {
  if (row.value === null) {
    return DASH;
  }
  if (typeof row.value === 'boolean') {
    return String(row.value);
  }
  if (typeof row.value === 'number') {
    return formatNumber(lang, row.value, 3);
  }
  return row.value;
};

export const ConstraintsCard = ({ payload }: { payload: unknown }) => {
  const { lang, t } = useI18n();
  const constraints = readConstraints(payload);
  if (constraints === null) {
    return <EmptyPayload />;
  }
  const groups = new Map<string, ConstraintRow[]>();
  for (const row of constraints.items) {
    const key = row.group ?? '';
    const bucket = groups.get(key);
    if (bucket === undefined) {
      groups.set(key, [row]);
      continue;
    }
    bucket.push(row);
  }

  return (
    <div className="jarvis-constraints">
      <p className="jarvis-constraints-case">{constraints.case}</p>
      {[...groups.entries()].map(([group, rows]) => (
        <section className="jarvis-constraints-group" key={group}>
          {group.length === 0 ? null : (
            <p className="jarvis-constraints-group-name">{group}</p>
          )}
          <dl className="jarvis-constraints-list">
            {rows.map((row) => (
              <div key={row.key} data-empty={row.empty ? 'true' : undefined}>
                <dt>{row.key}</dt>
                <dd>
                  <span className="jarvis-constraints-value">{cellOf(lang, row)}</span>
                  {row.unit === null ? null : (
                    <span className="jarvis-constraints-unit">{row.unit}</span>
                  )}
                  {row.source === null ? null : (
                    <span className="jarvis-constraints-source">{row.source}</span>
                  )}
                </dd>
              </div>
            ))}
          </dl>
        </section>
      ))}
      <p className="jarvis-constraints-total">
        {t('jarvis-cards.constraintsTotal', { count: String(constraints.items.length) })}
      </p>
    </div>
  );
};
