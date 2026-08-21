import { lazy, Suspense } from 'react';
import { useT } from '../i18n/I18nContext';
import { useConsole } from '../state/ConsoleContext';
import { ErrorBoundary } from '../ui/ErrorBoundary';
import { ViewStatus } from '../ui/ViewStatus';

const Council = lazy(() =>
  import('../views/Council').then((m) => ({ default: m.Council }))
);
const Rules = lazy(() => import('../views/Council').then((m) => ({ default: m.Rules })));

export const Decisions = () => {
  const t = useT();
  const { view } = useConsole();

  return (
    <ErrorBoundary>
      <Suspense fallback={<ViewStatus kind="loading" title={t('app.viewLoading')} />}>
        {view === 'council' && <Council />}
        {view === 'rules' && <Rules />}
      </Suspense>
    </ErrorBoundary>
  );
};
