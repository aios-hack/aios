import { lazy, Suspense, useMemo } from 'react';
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

export const Scene = () => {
  const t = useT();
  const { workspace, view, setView, viewsFor } = useConsole();
  const dataStatus = useWorkspaceData(workspace);

  const views = viewsFor(workspace);
  const options = useMemo(
    () => views.map((id) => ({ value: id, label: t(`view.${id}`) })),
    [views, t]
  );

  return (
    <section className="console-scene" data-workspace={workspace}>
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
      <div
        className="console-scene-body"
        data-testid="console-scene"
        data-data-status={dataStatus}
      >
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
