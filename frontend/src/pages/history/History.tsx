import { lazy, Suspense } from 'react';
import { useT } from '@/shared/i18n/I18nContext';
import { useRoute } from '@/shared/router/RouterProvider';
import { ErrorBoundary } from '@/shared/ui/ErrorBoundary';
import { ViewStatus } from '@/shared/ui/ViewStatus';
import { HistoryTable } from '@/pages/history-table/HistoryTable/HistoryTable';
import { HistoryViewProvider } from '@/pages/history-matrix/model/HistoryViewContext';

const Chronomap = lazy(() =>
  import('@/pages/history-matrix').then((m) => ({ default: m.Chronomap }))
);
const WallOfLives = lazy(() =>
  import('@/pages/history-wall').then((m) => ({ default: m.WallOfLives }))
);

export const History = () => {
  const t = useT();
  const { view } = useRoute();

  return (
    <HistoryViewProvider>
      <ErrorBoundary>
        <Suspense fallback={<ViewStatus kind="loading" title={t('app.viewLoading')} />}>
          {view === 'matrix' && <Chronomap />}
          {view === 'wall' && <WallOfLives />}
          {view === 'table' && <HistoryTable />}
        </Suspense>
      </ErrorBoundary>
    </HistoryViewProvider>
  );
};
