import { Scene } from './app/Scene';
import { TimeScale } from './app/TimeScale';
import { useDocumentTitle } from './app/useDocumentTitle';
import { useI18n } from './i18n/I18nContext';
import { useConsole } from './state/ConsoleContext';
import { usePlayback } from './state/PlaybackContext';
import { useTimeline } from './state/TimelineContext';
import { BrandLogo } from './ui/BrandLogo';
import { ErrorBoundary } from './ui/ErrorBoundary';
import { HeaderControls } from './ui/HeaderControls';
import { CommandPalette } from './ui/CommandPalette';
import { useWorkspaceRouting } from './app/useWorkspaceRouting';
import { ConsoleInspector } from './ui/Inspector';
import { ScenarioBadge } from './ui/ScenarioBadge';
import { StatusChip } from './ui/TrustBoard';
import { WorkspaceNav } from './ui/WorkspaceNav';
import './app/console.css';

const ConsoleShell = () => {
  const { t, lang } = useI18n();
  const { selectedWell } = useTimeline();
  const { workspace, view, setRoute } = useConsole();
  const { axisCollapsed } = usePlayback();
  useWorkspaceRouting({ workspace, view, setRoute });
  useDocumentTitle(t(`workspace.${workspace}`), t('app.documentTitle'), lang);

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
      <div className="console-area-inspector">
        <ErrorBoundary>
          <ConsoleInspector view={view} />
        </ErrorBoundary>
      </div>
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
