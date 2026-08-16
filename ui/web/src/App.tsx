import { useRef, useState } from 'react';
import { useI18n } from './i18n/I18nContext';
import { useTheme } from './theme/ThemeContext';
import { SyntheticBanner } from './ui/SyntheticBanner';
import { FieldMap } from './views/FieldMap';
import { LambdaGraph } from './views/LambdaGraph';
import { NpvRank } from './views/NpvRank';
import { Scenarios } from './views/Scenarios';
import { Timeline } from './views/Timeline';
import { WellCard } from './views/WellCard';

type ViewId = 'graph' | 'map' | 'steps' | 'npv' | 'scenarios';

const VIEWS: ViewId[] = ['graph', 'map', 'steps', 'npv', 'scenarios'];

export const App = () => {
  const { theme, toggleTheme } = useTheme();
  const { t, toggleLang } = useI18n();
  const [view, setView] = useState<ViewId>('graph');
  const tabRefs = useRef<Record<string, HTMLButtonElement | null>>({});

  const moveFocus = (from: ViewId, delta: number) => {
    const index = VIEWS.indexOf(from);
    const next = VIEWS[(index + delta + VIEWS.length) % VIEWS.length];
    setView(next);
    tabRefs.current[next]?.focus();
  };

  return (
    <div className="app">
      <header className="app-header">
        <div className="app-identity">
          <h1 className="app-title">{t('app.title')}</h1>
          <p className="app-subtitle">{t('app.subtitle')}</p>
        </div>
        <div className="app-actions">
          <button type="button" className="app-action-button" onClick={toggleTheme}>
            {theme === 'light' ? t('theme.dark') : t('theme.light')}
          </button>
          <button type="button" className="app-action-button" onClick={toggleLang}>
            {t('lang.toggle')}
          </button>
        </div>
      </header>
      <SyntheticBanner />
      <nav className="app-tabs" role="tablist" aria-label={t('tabs.label')}>
        {VIEWS.map((id) => (
          <button
            key={id}
            type="button"
            role="tab"
            id={`tab-${id}`}
            ref={(node) => {
              tabRefs.current[id] = node;
            }}
            className="app-tab"
            aria-selected={view === id}
            aria-pressed={view === id}
            aria-controls={`panel-${id}`}
            tabIndex={view === id ? 0 : -1}
            onClick={() => setView(id)}
            onKeyDown={(event) => {
              if (event.key === 'ArrowRight') {
                moveFocus(id, 1);
              }
              if (event.key === 'ArrowLeft') {
                moveFocus(id, -1);
              }
            }}
          >
            {t(`tab.${id}`)}
          </button>
        ))}
      </nav>
      <main
        className="app-main"
        id={`panel-${view}`}
        role="tabpanel"
        aria-labelledby={`tab-${view}`}
        tabIndex={-1}
      >
        <h2 className="app-view-title">{t(`${view}.title`)}</h2>
        {view === 'graph' && <LambdaGraph />}
        {view === 'map' && <FieldMap />}
        {view === 'steps' && <Timeline />}
        {view === 'npv' && <NpvRank />}
        {view === 'scenarios' && <Scenarios />}
      </main>
      <WellCard />
    </div>
  );
};
