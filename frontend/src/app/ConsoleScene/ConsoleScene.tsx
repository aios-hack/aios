import { Suspense, useEffect, useMemo } from 'react';
import { useT } from '@/shared/i18n/I18nContext';
import { type WorkspaceView } from '@/shared/router/routes';
import { useRoute } from '@/shared/router/RouterProvider';
import { ErrorBoundary } from '@/shared/ui/ErrorBoundary';
import { SegmentedControl } from '@/shared/ui/SegmentedControl';
import { ViewStatus } from '@/shared/ui/ViewStatus';
import { pageFor, pageKey } from '@/app/router/pages';
import { useWorkspaceData } from '@/app/ConsoleScene/useWorkspaceData';
import '@/app/ConsoleScene/ConsoleScene.css';

export const Scene = () => {
  const t = useT();
  const { workspace, view, setView, viewsFor } = useRoute();
  const dataStatus = useWorkspaceData(workspace);
  const Page = pageFor(workspace, view);

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
        key={pageKey(workspace, view)}
        className="console-scene-body app-view-enter"
        data-testid="console-scene"
        data-data-status={dataStatus}
      >
        <ErrorBoundary>
          <Suspense fallback={<ViewStatus kind="loading" title={t('app.viewLoading')} />}>
            {Page === null ? <ViewStatus kind="empty" title={t('view.label')} /> : <Page />}
          </Suspense>
        </ErrorBoundary>
      </div>
    </section>
  );
};
