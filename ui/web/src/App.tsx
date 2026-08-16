import { useState } from 'react';
import { useI18n } from './i18n/I18nContext';
import { useTheme } from './theme/ThemeContext';
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

  return (
    <div className="app">
      <header className="app-header">
        <h1 className="app-title">{t('app.title')}</h1>
        <div className="app-actions">
          <button type="button" className="app-action-button" onClick={toggleTheme}>
            {theme === 'light' ? t('theme.dark') : t('theme.light')}
          </button>
          <button type="button" className="app-action-button" onClick={toggleLang}>
            {t('lang.toggle')}
          </button>
        </div>
      </header>
      <nav className="app-tabs">
        {VIEWS.map((id) => (
          <button
            key={id}
            type="button"
            className="app-tab"
            aria-pressed={view === id}
            onClick={() => setView(id)}
          >
            {t(`tab.${id}`)}
          </button>
        ))}
      </nav>
      <main className="app-main">
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
