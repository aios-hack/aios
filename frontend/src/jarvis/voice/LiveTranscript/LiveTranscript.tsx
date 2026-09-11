import { useT } from '@/shared/i18n/I18nContext';
import { translateOr } from '@/jarvis/i18nFallback';
import { useJarvisVoice } from '@/jarvis/provider/contexts';
import './LiveTranscript.css';

export const LiveTranscript = () => {
  const t = useT();
  const {
    transcript,
    micOpen,
    sttError
  } = useJarvisVoice();
  if (!micOpen && transcript.text.length === 0 && sttError === null) {
    return null;
  }

  return (
    <p className="jarvis-transcript" role="status" aria-live="polite">
      {sttError === null ? (
        <span
          className="jarvis-transcript-text"
          data-final={transcript.final ? 'true' : undefined}
        >
          {transcript.text.length === 0 ? t('jarvis-voice.listening') : transcript.text}
        </span>
      ) : (
        <span className="jarvis-transcript-error">{translateOr(t, `jarvis-voice.stt.${sttError}`, 'jarvis-voice.stt.unknown')}</span>
      )}
    </p>
  );
};
