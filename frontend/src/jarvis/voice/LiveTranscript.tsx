import { useT } from '../../i18n/I18nContext';
import { translateOr } from '../i18nFallback';
import { useJarvis } from '../JarvisContext';
import './LiveTranscript.css';

export const LiveTranscript = () => {
  const t = useT();
  const { transcript, micOpen, sttError } = useJarvis();
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
          {transcript.text.length === 0 ? t('jarvis.listening') : transcript.text}
        </span>
      ) : (
        <span className="jarvis-transcript-error">{translateOr(t, `jarvis.stt.${sttError}`, 'jarvis.stt.unknown')}</span>
      )}
    </p>
  );
};
