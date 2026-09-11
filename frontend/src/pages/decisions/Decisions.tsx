import { lazy, Suspense } from 'react';
import { useT } from '@/shared/i18n/I18nContext';
import { useRoute } from '@/shared/router/RouterProvider';
import { ErrorBoundary } from '@/shared/ui/ErrorBoundary';
import { ViewStatus } from '@/shared/ui/ViewStatus';

const Council = lazy(() =>
  import('@/pages/council').then((m) => ({ default: m.Council }))
);
const Rules = lazy(() => import('@/pages/council').then((m) => ({ default: m.Rules })));

export const Decisions = () => {
  const t = useT();
  const { view } = useRoute();

  return (
    <ErrorBoundary>
      <Suspense fallback={<ViewStatus kind="loading" title={t('app.viewLoading')} />}>
        {view === 'council' && <Council />}
        {view === 'rules' && <Rules />}
      </Suspense>
    </ErrorBoundary>
  );
};
