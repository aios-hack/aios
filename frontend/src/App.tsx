import { useState } from 'react';
import { FieldStrip } from './app/FieldStrip';
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
import type { InspectorContext } from './ui/Inspector';
import { ScenarioBadge } from './ui/ScenarioBadge';
import { StatusChip } from './ui/TrustBoard';
import { WorkspaceNav } from './ui/WorkspaceNav';
import './app/console.css';

const ConsoleShell = () => {
  const { t, lang } = useI18n();
  const { selectedWell } = useTimeline();
  const { workspace, view, setWorkspace, setView } = useConsole();
  const { axisCollapsed } = usePlayback();
  const [scenarioContext, setScenarioContext] = useState<InspectorContext | null>(null);
  useWorkspaceRouting({ workspace, view, setWorkspace, setView });
  useDocumentTitle(t(`workspace.${workspace}`), t('app.documentTitle'), lang);

  const inspectorOpen = selectedWell !== null || scenarioContext !== null;
  const stripVisible = workspace === 'field' || workspace === 'history';

  return (
    <div
      className="app console"
      data-inspector={inspectorOpen ? 'open' : 'closed'}
      data-strip={stripVisible ? 'shown' : 'hidden'}
      data-axis={axisCollapsed ? 'collapsed' : undefined}
    >
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
          <ScenarioBadge
            onOpenDetails={(scenarioId) => setScenarioContext({ kind: 'scenario', scenarioId })}
          />
        </ErrorBoundary>
        <HeaderControls />
      </header>
      <ErrorBoundary>
        <FieldStrip />
      </ErrorBoundary>
      <div className="console-area-nav">
        <WorkspaceNav />
      </div>
      <main className="console-area-scene console-main">
        <Scene />
      </main>
      <div className="console-area-inspector">
        <ErrorBoundary>
          <ConsoleInspector
            scenarioContext={scenarioContext}
            onCloseScenario={() => setScenarioContext(null)}
          />
        </ErrorBoundary>
      </div>
      <div className="console-area-timeaxis">
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
