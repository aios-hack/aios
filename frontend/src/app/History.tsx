import { lazy, Suspense } from 'react';
import { useT } from '../i18n/I18nContext';
import { useConsole } from '../state/ConsoleContext';
import { ErrorBoundary } from '../ui/ErrorBoundary';
import { ViewStatus } from '../ui/ViewStatus';
import { HistoryTable } from '../views/Timeline/HistoryTable';
import { HistoryViewProvider } from './HistoryViewContext';

const Chronomap = lazy(() =>
  import('../views/Chronomap').then((m) => ({ default: m.Chronomap }))
);
const WallOfLives = lazy(() =>
  import('../views/WallOfLives').then((m) => ({ default: m.WallOfLives }))
);

export const History = () => {
  const t = useT();
  const { view } = useConsole();

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
