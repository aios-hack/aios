import { MoonStarsIcon, SunIcon } from '@phosphor-icons/react';
import { useI18n } from '../../i18n/I18nContext';
import { useTheme } from '../../theme/ThemeContext';
import './HeaderControls.css';

export const HeaderControls = () => {
  const { theme, toggleTheme } = useTheme();
  const { lang, toggleLang, t } = useI18n();
  const nextTheme = theme === 'light' ? 'dark' : 'light';

  return (
    <div className="header-controls">
      <div className="icon-island">
        <button
          type="button"
          className="icon-button"
          data-guide="header-theme"
          onClick={toggleTheme}
          aria-label={t(`theme.${nextTheme}`)}
          title={t(`theme.${nextTheme}`)}
        >
          <span className="icon-button-glyph" aria-hidden="true">
            {theme === 'light' ? (
              <MoonStarsIcon size={15} weight="duotone" />
            ) : (
              <SunIcon size={15} weight="duotone" />
            )}
          </span>
        </button>
      </div>
      <button
        type="button"
        className="lang-toggle"
        data-guide="header-language"
        onClick={toggleLang}
        aria-label={t('lang.switch')}
        title={t('lang.switch')}
        data-lang={lang}
      >
        <span className="lang-thumb" aria-hidden="true" />
        <span className="lang-code" data-code="ru">
          RU
        </span>
        <span className="lang-code" data-code="en">
          EN
        </span>
      </button>
    </div>
  );
};
