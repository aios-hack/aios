import { lazy, Suspense, useEffect, useMemo } from 'react';
import { useT } from '../i18n/I18nContext';
import { useConsole, type WorkspaceView } from '../state/ConsoleContext';
import { ErrorBoundary } from '../ui/ErrorBoundary';
import { SegmentedControl } from '../ui/SegmentedControl';
import { ViewStatus } from '../ui/ViewStatus';
import { Decisions } from './Decisions';
import { useWorkspaceData } from './useWorkspaceData';
import { History } from './History';

const FieldProjection = lazy(() =>
  import('../views/FieldProjection').then((m) => ({ default: m.FieldProjection }))
);
const Money = lazy(() => import('../views/Money').then((m) => ({ default: m.Money })));
const Overview = lazy(() => import('../views/Overview').then((m) => ({ default: m.Overview })));

export const Scene = () => {
  const t = useT();
  const { workspace, view, setView, viewsFor } = useConsole();
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
              <FieldProjection />
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
