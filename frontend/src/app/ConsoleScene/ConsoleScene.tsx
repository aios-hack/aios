import { lazy, Suspense, useEffect, useMemo } from 'react';
import { useT } from '@/shared/i18n/I18nContext';
import { type WorkspaceView } from '@/shared/router/routes';
import { useRoute } from '@/shared/router/RouterProvider';
import { ErrorBoundary } from '@/shared/ui/ErrorBoundary';
import { SegmentedControl } from '@/shared/ui/SegmentedControl';
import { ViewStatus } from '@/shared/ui/ViewStatus';
import { Decisions } from '@/pages/decisions/Decisions';
import { useWorkspaceData } from '@/app/ConsoleScene/useWorkspaceData';
import { History } from '@/pages/history/History';

const FieldProjection = lazy(() =>
  import('@/pages/field-projection').then((m) => ({ default: m.FieldProjection }))
);
const FieldMaps = lazy(() =>
  import('@/pages/field-maps').then((m) => ({ default: m.FieldMaps }))
);
const Money = lazy(() => import('@/pages/money').then((m) => ({ default: m.Money })));
const Overview = lazy(() => import('@/pages/overview').then((m) => ({ default: m.Overview })));

export const Scene = () => {
  const t = useT();
  const { workspace, view, setView, viewsFor } = useRoute();
  const dataStatus = useWorkspaceData(workspace);

  useEffect(() => {
    const main = document.querySelector('.console-main');
    if (main !== null) {
      main.scrollTop = 0;
    }
  }, [workspace, view]);

  const views = viewsFor(workspace);
  const options = useMemo(
    () => views.map((id) => ({ value: id, label: t(`view.${id}`) })),
    [views, t]
  );

  return (
    <section className="console-scene" data-workspace={workspace}>
      <div className="console-scene-head">
        <div className="console-scene-identity">
          <h2 className="console-scene-title">{t(`workspace.${workspace}`)}</h2>
          <p className="console-scene-lead">{t(`workspace.${workspace}.lead`)}</p>
        </div>
        {views.length > 1 && (
          <div className="console-scene-bar">
            <SegmentedControl<WorkspaceView>
              options={options}
              active={view}
              label={t('view.label')}
              onSelect={setView}
            />
          </div>
        )}
      </div>
      <div
        key={`${workspace}/${view}`}
        className="console-scene-body app-view-enter"
        data-testid="console-scene"
        data-data-status={dataStatus}
      >
        {workspace === 'overview' && (
          <ErrorBoundary>
            <Suspense fallback={<ViewStatus kind="loading" title={t('app.viewLoading')} />}>
              <Overview />
            </Suspense>
          </ErrorBoundary>
        )}
        {workspace === 'field' && (
          <ErrorBoundary>
            <Suspense fallback={<ViewStatus kind="loading" title={t('app.viewLoading')} />}>
              {view === 'maps' ? <FieldMaps /> : <FieldProjection />}
            </Suspense>
          </ErrorBoundary>
        )}
        {workspace === 'history' && <History />}
        {workspace === 'decisions' && <Decisions />}
        {workspace === 'money' && (
          <ErrorBoundary>
            <Suspense fallback={<ViewStatus kind="loading" title={t('app.viewLoading')} />}>
              <Money />
            </Suspense>
          </ErrorBoundary>
        )}
      </div>
    </section>
  );
};
