import { MoonStarsIcon, SunIcon } from '@phosphor-icons/react';
import { useI18n } from '@/shared/i18n/I18nContext';
import { useTheme } from '@/shared/theme/ThemeContext';
import { IconButton, IconIsland } from '@/shared/ui/IconButton';
import './HeaderControls.css';

export const HeaderControls = () => {
  const { theme, toggleTheme } = useTheme();
  const { lang, toggleLang, t } = useI18n();
  const nextTheme = theme === 'light' ? 'dark' : 'light';

  return (
    <div className="header-controls">
      <IconIsland>
        <IconButton
          glyph
          data-guide="header-theme"
          onClick={toggleTheme}
          label={t(`theme.${nextTheme}`)}
        >
          {theme === 'light' ? (
            <MoonStarsIcon size={15} weight="duotone" />
          ) : (
            <SunIcon size={15} weight="duotone" />
          )}
        </IconButton>
      </IconIsland>
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
