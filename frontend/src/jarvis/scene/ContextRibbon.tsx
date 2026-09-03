import { XIcon } from '@phosphor-icons/react';
import { useI18n } from '../../i18n/I18nContext';
import { DASH, formatStepDate } from '../../ui/format';
import { useJarvis } from '../JarvisContext';
import './ContextRibbon.css';

export const ContextRibbon = () => {
  const { lang, t, toggleLang } = useI18n();
  const { askContext, close, degraded, speakEnabled, toggleSpeak } = useJarvis();

  return (
    <header className="jarvis-ribbon" aria-label={t('jarvis.contextLabel')}>
      <dl className="jarvis-ribbon-facts">
        <div>
          <dt>{t('jarvis.contextScenario')}</dt>
          <dd>{askContext.scenario}</dd>
        </div>
        <div>
          <dt>{t('jarvis.contextStep')}</dt>
          <dd>
            {askContext.date.length === 0 ? DASH : formatStepDate(lang, askContext.date)}
          </dd>
        </div>
        <div>
          <dt>{t('jarvis.contextWell')}</dt>
          <dd>{askContext.selected_well ?? t('jarvis.contextNoWell')}</dd>
        </div>
      </dl>
      {degraded ? <p className="jarvis-ribbon-demo">{t('jarvis.demoMode')}</p> : null}
      <div className="jarvis-ribbon-controls">
        <button
          type="button"
          className="jarvis-ribbon-button"
          aria-pressed={speakEnabled}
          onClick={toggleSpeak}
        >
          {speakEnabled ? t('jarvis.speakOn') : t('jarvis.speakOff')}
        </button>
        <button type="button" className="jarvis-ribbon-button" onClick={toggleLang}>
          {lang === 'ru' ? 'en' : 'ru'}
        </button>
        <button
          type="button"
          className="jarvis-ribbon-close"
          aria-label={t('jarvis.closeLabel')}
          onClick={close}
        >
          <XIcon size={16} weight="bold" aria-hidden="true" />
        </button>
      </div>
    </header>
  );
};
