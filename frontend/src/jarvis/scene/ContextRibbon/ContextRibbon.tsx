import { useI18n } from '@/shared/i18n/I18nContext';
import { DASH, formatStepDate } from '@/shared/lib/format';
import { useJarvisSessionContext, useJarvisVoice } from '@/jarvis/provider/contexts';
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
    scenes
  } = useJarvisSessionContext();
  const {
    speakEnabled,
    toggleSpeak,
    confirmVoice,
    toggleConfirmVoice
  } = useJarvisVoice();
  const answer = scenes.scenes[scenes.activeIndex]?.answer ?? null;

  return (
    <header className="jarvis-ribbon" aria-label={t('jarvis-screen.contextLabel')}>
      <dl className="jarvis-ribbon-facts">
        <div>
          <dt>{t('jarvis-screen.contextScenario')}</dt>
          <dd>{askContext.scenario}</dd>
        </div>
        <div>
          <dt>{t('jarvis-screen.contextStep')}</dt>
          <dd>
            {askContext.date.length === 0 ? DASH : formatStepDate(lang, askContext.date)}
          </dd>
        </div>
        <div>
          <dt>{t('jarvis-screen.contextWell')}</dt>
          <dd>{askContext.selected_well ?? t('jarvis-screen.contextNoWell')}</dd>
        </div>
      </dl>
      <ul className="jarvis-ribbon-chips" aria-label={t('jarvis-screen.capabilitiesLabel')}>
        <li className="jarvis-ribbon-chip" data-on={capabilities.ok ? 'true' : 'false'}>
          {capabilities.ok ? t('jarvis-screen.chipLive') : t('jarvis-screen.chipOffline')}
        </li>
        <li className="jarvis-ribbon-chip" data-on={capabilities.tts ? 'true' : 'false'}>
          {t('jarvis-screen.chipTts')}
        </li>
        <li
          className="jarvis-ribbon-chip"
          data-on={capabilities.stt === 'none' ? 'false' : 'true'}
        >
          {t('jarvis-screen.chipStt')}
        </li>
        {capabilities.docs > 0 ? (
          <li className="jarvis-ribbon-chip" data-on="true">
            {t('jarvis-screen.chipDocs', { count: String(capabilities.docs) })}
          </li>
        ) : null}
      </ul>
      <div className="jarvis-ribbon-controls">
        {speaking ? (
          <button type="button" className="jarvis-ribbon-button" onClick={onStop}>
            {t('jarvis-voice.speakStop')}
          </button>
        ) : null}
        {answer === null || answer.trim().length === 0 ? null : (
          <button type="button" className="jarvis-ribbon-button" onClick={onReadAll}>
            {t('jarvis-voice.speakAnswer')}
          </button>
        )}
        <button
          type="button"
          className="jarvis-ribbon-button"
          aria-pressed={confirmVoice}
          title={t('jarvis-voice.voiceModeHint')}
          onClick={toggleConfirmVoice}
        >
          {confirmVoice ? t('jarvis-voice.voiceConfirm') : t('jarvis-voice.voiceInstant')}
        </button>
        <button
          type="button"
          className="jarvis-ribbon-button"
          aria-pressed={speakEnabled}
          onClick={toggleSpeak}
        >
          {speakEnabled ? t('jarvis-voice.speakOn') : t('jarvis-voice.speakOff')}
        </button>
        <button type="button" className="jarvis-ribbon-button" onClick={toggleLang}>
          {lang === 'ru' ? 'en' : 'ru'}
        </button>
      </div>
    </header>
  );
};
