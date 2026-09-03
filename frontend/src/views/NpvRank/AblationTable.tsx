import { memo, useCallback, useMemo, useRef, useState, type CSSProperties } from 'react';
import type { AblationFile } from '../../api/types';
import { useI18n } from '../../i18n/I18nContext';
import { formatNumber, formatPercent } from '../../ui/format';
import { LegendPopover } from '../../ui/Legend';
import { SortHeader } from '../../ui/SortHeader';
import { coverageOf, leadRatio, toEntries } from './ablation';
import { AblationRow } from './AblationRow';
import {
  isNumericAblationKey,
  sortAblationEntries,
  type AblationSortDir,
  type AblationSortKey
} from './ablationSorting';
import './AblationTable.css';

interface AblationTableProps {
  data: AblationFile;
  standalone?: boolean;
}

const COLUMNS: readonly AblationSortKey[] = [
  'rule',
  'name',
  'statement',
  'delta',
  'share'
];

const AblationTableView = ({ data, standalone = false }: AblationTableProps) => {
  const { t, lang } = useI18n();
  const [sortKey, setSortKey] = useState<AblationSortKey>('delta');
  const [dir, setDir] = useState<AblationSortDir>('desc');

  const sortKeyRef = useRef(sortKey);
  sortKeyRef.current = sortKey;

  const onSort = useCallback((key: AblationSortKey) => {
    if (key === sortKeyRef.current) {
      setDir((value) => (value === 'desc' ? 'asc' : 'desc'));
      return;
    }
    setSortKey(key);
    setDir(isNumericAblationKey(key) ? 'desc' : 'asc');
  }, []);

  const entries = useMemo(() => toEntries(data.rules), [data.rules]);
  const coverage = useMemo(() => coverageOf(entries), [entries]);

  const nameOf = useCallback(
    (rule: string): string => {
      const key = `npv.ablation.rule.${rule}.name`;
      const text = t(key);
      return text === key ? rule : text;
    },
    [t]
  );

  const statementOf = useCallback(
    (rule: string): string => {
      const key = `npv.ablation.rule.${rule}.statement`;
      const text = t(key);
      return text === key ? '' : text;
    },
    [t]
  );

  const rows = useMemo(
    () =>
      sortAblationEntries(entries, sortKey, dir, { name: nameOf, statement: statementOf }),
    [entries, sortKey, dir, nameOf, statementOf]
  );

  const top = useMemo(
    () =>
      entries.reduce<(typeof entries)[number] | null>(
        (acc, entry) =>
          entry.delta !== null && entry.delta > (acc?.delta ?? 0) ? entry : acc,
        null
      ),
    [entries]
  );

  return (
    <section className="abl" aria-labelledby="abl-title" data-standalone={standalone}>
      <header className="abl-head">
        <div className="abl-headline">
          <h3 className="abl-title" id="abl-title">
            {t('npv.ablation.title')}
          </h3>
          <p className="abl-intro">{t('npv.ablation.intro')}</p>
        </div>
        <div className="abl-head-aside">
          <p className="abl-total">
            <span className="abl-total-label">{t('npv.ablation.total')}</span>
            <span className="abl-total-amount">
              <span className="abl-total-value" data-testid="abl-total">
                {formatNumber(lang, data.npv_total)}
              </span>
              <span className="abl-total-unit">{t('npv.ablation.totalUnit')}</span>
            </span>
          </p>
          <LegendPopover
            triggerLabel={t('toolbar.legend')}
            title={t('npv.ablation.legend.title')}
            notes={[
              { text: t('npv.ablation.legend.delta') },
              { text: t('npv.ablation.legend.bar') },
              { text: t('npv.ablation.legend.share') },
              { text: t('npv.ablation.legend.unmeasured') },
              { text: t('npv.ablation.legend.zero') },
              { text: t('npv.ablation.legend.disabled') }
            ]}
          />
        </div>
      </header>

      <div
        className="abl-table-wrap"
        data-guide={standalone ? 'rules-table' : 'npv-ablation-table'}
      >
        <table className="abl-table">
          <caption className="abl-caption">{t('npv.ablation.tableCaption')}</caption>
          <thead>
            <tr>
              {COLUMNS.map((key) => (
                <SortHeader
                  key={key}
                  prefix="abl"
                  label={t(`npv.ablation.column.${key}`)}
                  active={sortKey === key}
                  dir={dir}
                  title={t(
                    sortKey === key && dir === 'asc'
                      ? 'council.sort.asc'
                      : 'council.sort.desc'
                  )}
                  numericClass={
                    isNumericAblationKey(key) ? `abl-cell-${key}` : `abl-col-${key}`
                  }
                  onSort={() => onSort(key)}
                />
              ))}
            </tr>
          </thead>
          <tbody key={`${sortKey}/${dir}`}>
            {rows.map((entry, index) => (
              <AblationRow
                key={entry.rule}
                entry={entry}
                index={index}
                ratio={leadRatio(entry, entries)}
                name={nameOf(entry.rule)}
                statement={statementOf(entry.rule)}
                lang={lang}
                t={t}
              />
            ))}
          </tbody>
        </table>
      </div>

      <footer className="abl-summary" data-testid="abl-coverage">
        <div className="abl-summary-stat">
          <span className="abl-summary-label">{t('npv.ablation.summary.measured')}</span>
          <span className="abl-summary-value">
            {coverage.measured}
            <span className="abl-summary-unit">
              {t('npv.ablation.summary.ofTotal', { total: entries.length })}
            </span>
          </span>
        </div>
        <div className="abl-summary-stat">
          <span className="abl-summary-label">{t('npv.ablation.summary.explained')}</span>
          <span className="abl-summary-gauge">
            <span className="abl-summary-meter" aria-hidden="true">
              <span
                className="abl-summary-fill"
                style={
                  {
                    '--abl-bar-ratio': Math.min(coverage.accountedShare, 1)
                  } as CSSProperties
                }
              />
            </span>
            <span className="abl-summary-value">
              {formatPercent(lang, coverage.accountedShare)}
            </span>
          </span>
        </div>
        {top !== null && (
          <div className="abl-summary-stat">
            <span className="abl-summary-label">{t('npv.ablation.summary.top')}</span>
            <span className="abl-summary-value abl-summary-top">
              <span className="abl-summary-top-code">{top.rule}</span>
              <span className="abl-summary-top-name">{nameOf(top.rule)}</span>
            </span>
          </div>
        )}
        <p className="abl-summary-gap">
          {coverage.unmeasured === 0
            ? t('npv.ablation.summary.gapNone')
            : t('npv.ablation.summary.gap', { count: coverage.unmeasured })}
        </p>
      </footer>
    </section>
  );
};

export const AblationTable = memo(AblationTableView);
