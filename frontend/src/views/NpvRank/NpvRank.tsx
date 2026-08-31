import { useCallback, useRef, useState } from 'react';
import { useDataset } from '../../data';
import { useT } from '../../i18n/I18nContext';
import { useTimeline } from '../../state/TimelineContext';
import { LegendPopover } from '../../ui/Legend';
import { ViewStatus } from '../../ui/ViewStatus';
import { ViewToolbar } from '../../ui/ViewToolbar';
import { AblationTable } from './AblationTable';
import { NpvTable } from './NpvTable';
import { TaxModeSwitch } from './TaxModeSwitch';
import type { NpvSortKey, SortDir, TaxMode } from './types';
import './NpvRank.css';

export const NpvRank = () => {
  const t = useT();
  const { selectedWell, selectWell } = useTimeline();
  const npv = useDataset('npv');
  const ablation = useDataset('ablation');
  const [mode, setMode] = useState<TaxMode>('preTax');
  const [sortKey, setSortKey] = useState<NpvSortKey>('value');
  const [dir, setDir] = useState<SortDir>('desc');

  const sortKeyRef = useRef(sortKey);
  sortKeyRef.current = sortKey;

  const onSort = useCallback((key: NpvSortKey) => {
    if (key === sortKeyRef.current) {
      setDir((value) => (value === 'desc' ? 'asc' : 'desc'));
      return;
    }
    setSortKey(key);
    setDir(key === 'well' ? 'asc' : 'desc');
  }, []);

  if (npv.status === 'loading') {
    return <ViewStatus kind="loading" title={t('npv.loading')} />;
  }
  if (npv.status === 'error') {
    return <ViewStatus kind="error" title={t('npv.error')} hint={t('npv.errorHint')} />;
  }

  return (
    <section className="npv">
      <ViewToolbar
        left={
          <div className="npv-controls">
            <TaxModeSwitch mode={mode} onChange={setMode} />
            <span className="npv-badge" data-mode={mode}>
              {t(`npv.badge.${mode}`)}
            </span>
          </div>
        }
        right={
          <LegendPopover
            triggerLabel={t('toolbar.legend')}
            title={t('npv.legend.title')}
            swatches={[
              {
                key: 'positive',
                color: 'var(--color-accent)',
                label: t('npv.legend.positive')
              },
              {
                key: 'negative',
                color: 'var(--color-danger)',
                label: t('npv.legend.negative')
              }
            ]}
            notes={[
              { text: t('npv.legend.bar') },
              { text: t('npv.legend.mode') },
              { text: t('npv.legend.selected') }
            ]}
          />
        }
      />
      <NpvTable
        data={npv.data}
        mode={mode}
        sortKey={sortKey}
        dir={dir}
        onSort={onSort}
        selectedWell={selectedWell}
        onSelectWell={selectWell}
      />
      {ablation.status === 'ready' && <AblationTable data={ablation.data} />}
      {ablation.status === 'error' && (
        <ViewStatus
          kind="error"
          title={t('npv.ablation.error')}
          hint={t('npv.ablation.errorHint')}
        />
      )}
      {ablation.status === 'loading' && (
        <ViewStatus kind="loading" title={t('npv.ablation.loading')} />
      )}
    </section>
  );
};
