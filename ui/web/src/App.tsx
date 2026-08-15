import { useI18n } from './i18n/I18nContext';
import { useTheme } from './theme/ThemeContext';
import { FieldMap } from './views/FieldMap';

export const App = () => {
  const { theme, toggleTheme } = useTheme();
  const { t, toggleLang } = useI18n();

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
      <main className="app-main">
        <h2 className="app-view-title">{t('map.title')}</h2>
        <FieldMap />
      </main>
    </div>
  );
};
