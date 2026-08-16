import { useEffect, useState } from 'react';
import type { NpvFile } from '../../api/types';
import { useT } from '../../i18n/I18nContext';
import { useTimeline, type ResourceState } from '../../state/TimelineContext';
import { ViewStatus } from '../../ui/ViewStatus';
import { NpvTable } from './NpvTable';
import { TaxModeSwitch } from './TaxModeSwitch';
import type { SortDir, TaxMode } from './types';
import './NpvRank.css';

const isNpvFile = (data: unknown): data is NpvFile =>
  typeof data === 'object' &&
  data !== null &&
  Array.isArray((data as { wells?: unknown }).wells) &&
  (data as { wells: unknown[] }).wells.length > 0 &&
  typeof (data as { total?: unknown }).total === 'object';

const useNpvFile = (): ResourceState<NpvFile> => {
  const [state, setState] = useState<ResourceState<NpvFile>>({ status: 'loading' });

  useEffect(() => {
    let cancelled = false;
    fetch('/data/npv.json')
      .then((response) => {
        if (!response.ok) {
          throw new Error(String(response.status));
        }
        return response.json();
      })
      .then((data: unknown) => {
        if (!cancelled) {
          setState(isNpvFile(data) ? { status: 'ready', data } : { status: 'error' });
        }
      })
      .catch(() => {
        if (!cancelled) {
          setState({ status: 'error' });
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return state;
};

export const NpvRank = () => {
  const t = useT();
  const { selectedWell, selectWell } = useTimeline();
  const npv = useNpvFile();
  const [mode, setMode] = useState<TaxMode>('preTax');
  const [dir, setDir] = useState<SortDir>('desc');

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
        dir={dir}
        onToggleDir={() => setDir((value) => (value === 'desc' ? 'asc' : 'desc'))}
        selectedWell={selectedWell}
        onSelectWell={selectWell}
      />
    </section>
  );
};
