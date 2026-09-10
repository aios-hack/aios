import { useI18n } from '../../i18n/I18nContext';
import { DASH, formatStepDate } from '../../ui/format';
import { useJarvis } from '../JarvisContext';
import './ContextRibbon.css';

interface ContextRibbonProps {
  speaking: boolean;
  onStop: () => void;
  onReadAll: () => void;
}

export const ContextRibbon = ({ speaking, onStop, onReadAll }: ContextRibbonProps) => {
  const { lang, t, toggleLang } = useI18n();
  const {
    askContext,
    capabilities,
    speakEnabled,
    toggleSpeak,
    confirmVoice,
    toggleConfirmVoice,
    scenes
  } = useJarvis();
  const answer = scenes.scenes[scenes.activeIndex]?.answer ?? null;

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
      <ul className="jarvis-ribbon-chips" aria-label={t('jarvis.capabilitiesLabel')}>
        <li className="jarvis-ribbon-chip" data-on={capabilities.ok ? 'true' : 'false'}>
          {capabilities.ok ? t('jarvis.chipLive') : t('jarvis.chipOffline')}
        </li>
        <li className="jarvis-ribbon-chip" data-on={capabilities.tts ? 'true' : 'false'}>
          {t('jarvis.chipTts')}
        </li>
        <li
          className="jarvis-ribbon-chip"
          data-on={capabilities.stt === 'none' ? 'false' : 'true'}
        >
          {t('jarvis.chipStt')}
        </li>
        {capabilities.docs > 0 ? (
          <li className="jarvis-ribbon-chip" data-on="true">
            {t('jarvis.chipDocs', { count: String(capabilities.docs) })}
          </li>
        ) : null}
      </ul>
      <div className="jarvis-ribbon-controls">
        {speaking ? (
          <button type="button" className="jarvis-ribbon-button" onClick={onStop}>
            {t('jarvis.speakStop')}
          </button>
        ) : null}
        {answer === null || answer.trim().length === 0 ? null : (
          <button type="button" className="jarvis-ribbon-button" onClick={onReadAll}>
            {t('jarvis.speakAnswer')}
          </button>
        )}
        <button
          type="button"
          className="jarvis-ribbon-button"
          aria-pressed={confirmVoice}
          title={t('jarvis.voiceModeHint')}
          onClick={toggleConfirmVoice}
        >
          {confirmVoice ? t('jarvis.voiceConfirm') : t('jarvis.voiceInstant')}
        </button>
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
      </div>
    </header>
  );
};
