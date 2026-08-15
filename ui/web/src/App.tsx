import { useState } from 'react';
import { useI18n } from './i18n/I18nContext';
import { useTheme } from './theme/ThemeContext';
import { FieldMap } from './views/FieldMap';
import { Timeline } from './views/Timeline';

type ViewId = 'map' | 'steps';

export const App = () => {
  const { theme, toggleTheme } = useTheme();
  const { t, toggleLang } = useI18n();
  const [view, setView] = useState<ViewId>('map');

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
        <button
          type="button"
          className="app-tab"
          aria-pressed={view === 'map'}
          onClick={() => setView('map')}
        >
          {t('tab.map')}
        </button>
        <button
          type="button"
          className="app-tab"
          aria-pressed={view === 'steps'}
          onClick={() => setView('steps')}
        >
          {t('tab.steps')}
        </button>
      </nav>
      <main className="app-main">
        <h2 className="app-view-title">
          {view === 'map' ? t('map.title') : t('steps.title')}
        </h2>
        {view === 'map' ? <FieldMap /> : <Timeline />}
      </main>
    </div>
  );
};
