import { Scene } from '@/app/ConsoleScene/ConsoleScene';
import { TimeScale } from '@/features/timeline-player/ui/TimeScale/TimeScale';
import { useDocumentTitle } from '@/app/router/useDocumentTitle';
import { useI18n } from '@/shared/i18n/I18nContext';
import { useRoute } from '@/shared/router/RouterProvider';
import { DEFAULT_SCENARIO_ID, useScenario } from '@/entities/scenarios/model/ScenarioContext';
import { usePlayback } from '@/entities/timeline/model/PlaybackContext';
import { useTimeline } from '@/entities/timeline/model/TimelineContext';
import { BrandLogo } from '@/shared/ui/BrandLogo';
import { ErrorBoundary } from '@/shared/ui/ErrorBoundary';
import { HeaderControls } from '@/features/header-controls/ui';
import { CommandPalette } from '@/features/command-palette/ui';
import { useWorkspaceRouting } from '@/app/router/useWorkspaceRouting';
import { ConsoleInspector } from '@/features/inspector/ui';
import { ScenarioBadge } from '@/features/scenario-switch/ui/ScenarioBadge';
import { StatusChip } from '@/features/trust-board/ui';
import { WorkspaceNav } from '@/features/workspace-nav/ui';
import '@/app/ConsoleScene/ConsoleShell.css';

const ConsoleShell = () => {
  const { t, lang } = useI18n();
  const { selectedWell } = useTimeline();
  const { workspace, view, setRoute } = useRoute();
  const { axisCollapsed } = usePlayback();
  const { activeId } = useScenario();
  useWorkspaceRouting({ workspace, view, setRoute });
  useDocumentTitle(
    {
      section: t(`workspace.${workspace}`),
      view: t(`view.${view}`),
      scenario: activeId === DEFAULT_SCENARIO_ID ? undefined : activeId,
      suffix: t('app.documentTitle')
    },
    lang
  );

  const inspectorOpen = selectedWell !== null;

  return (
    <div
      className="app console"
      data-inspector={inspectorOpen ? 'open' : 'closed'}
      data-axis={axisCollapsed ? 'collapsed' : undefined}
    >
      <button
        type="button"
        className="skip-link"
        onClick={() => {
          document.getElementById('console-timeaxis')?.focus();
        }}
      >
        {t('app.skipToTime')}
      </button>
      <header className="console-area-header app-header">
        <BrandLogo />
        <div className="app-identity">
          <h1 className="app-title">
            <span className="app-title-accent">AIOS</span>
            <span className="app-title-rest">{t('app.title')}</span>
          </h1>
          <p className="app-subtitle">{t('app.subtitle')}</p>
        </div>
        <ErrorBoundary>
          <StatusChip />
        </ErrorBoundary>
        <ErrorBoundary>
          <ScenarioBadge onOpenLibrary={() => setRoute('money', 'comparison')} />
        </ErrorBoundary>
        <HeaderControls />
      </header>
      <div className="console-area-nav">
        <WorkspaceNav />
      </div>
      <main className="console-area-scene console-main">
        <Scene />
      </main>
      <ErrorBoundary>
        <ConsoleInspector view={view} />
      </ErrorBoundary>
      <div className="console-area-timeaxis" id="console-timeaxis" tabIndex={-1}>
        <ErrorBoundary>
          <TimeScale />
        </ErrorBoundary>
      </div>
      <ErrorBoundary silent>
        <CommandPalette />
      </ErrorBoundary>
    </div>
  );
};

export const App = () => <ConsoleShell />;
