import { useMemo, useState } from 'react';
import { useComparison, useRuns } from '@/entities';
import { useT } from '@/shared/i18n/I18nContext';
import { ViewStatus } from '@/shared/ui/ViewStatus';
import { BaselineTable } from '@/pages/money-comparison/ui/BaselineTable/BaselineTable';
import { championOf, RunList } from '@/pages/money-comparison/ui/RunList/RunList';
import '@/pages/money-comparison/ui/RunList/RunList.css';

export const RunsPanel = () => {
  const t = useT();
  const runs = useRuns();
  const rows = useMemo(() => (runs.status === 'ready' ? runs.data.runs : []), [runs]);
  const [picked, setPicked] = useState<string | null>(null);
  const selected = picked ?? championOf(rows) ?? rows[0]?.run_id ?? null;
  const comparison = useComparison(selected);

  if (runs.status === 'loading') {
    return <ViewStatus kind="loading" title={t('npv.runs.loading')} />;
  }
  if (runs.status === 'error') {
    return (
      <ViewStatus kind="empty" title={t('npv.runs.offline')} hint={t('npv.runs.offlineHint')} />
    );
  }
  if (rows.length === 0) {
    return <ViewStatus kind="empty" title={t('npv.runs.empty')} hint={t('npv.runs.emptyHint')} />;
  }

  return (
    <section className="runs-panel" data-testid="runs-panel" data-guide="money-runs">
      <RunList rows={rows} selected={selected} onSelect={setPicked} />
      {comparison.status === 'ready' ? (
        <BaselineTable file={comparison.data} />
      ) : (
        <p className="run-compare-missing" data-testid="run-compare-missing">
          {t('npv.compare.missing', { run: selected ?? '' })}
        </p>
      )}
    </section>
  );
};
