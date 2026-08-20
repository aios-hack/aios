import { useCallback, useRef, useState } from 'react';
import { useDataset } from '../../data';
import { useT } from '../../i18n/I18nContext';
import { useTimeline } from '../../state/TimelineContext';
import { ViewStatus } from '../../ui/ViewStatus';
import { NpvTable } from './NpvTable';
import { TaxModeSwitch } from './TaxModeSwitch';
import type { NpvSortKey, SortDir, TaxMode } from './types';
import './NpvRank.css';

export const NpvRank = () => {
  const t = useT();
  const { selectedWell, selectWell } = useTimeline();
  const npv = useDataset('npv');
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
      <div className="npv-controls">
        <TaxModeSwitch mode={mode} onChange={setMode} />
        <span className="npv-badge" data-mode={mode}>
          {t(`npv.badge.${mode}`)}
        </span>
      </div>
      <NpvTable
        data={npv.data}
        mode={mode}
        sortKey={sortKey}
        dir={dir}
        onSort={onSort}
        selectedWell={selectedWell}
        onSelectWell={selectWell}
      />
    </section>
  );
};
