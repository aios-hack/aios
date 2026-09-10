import { useCallback, useEffect } from 'react';
import { useI18n } from '../../i18n/I18nContext';
import { isEditableTarget } from '../../app/useHotkeys';
import { useJarvis } from '../JarvisContext';
import { useMicLevel } from './useMicLevel';
import { useRecorder } from './useRecorder';
import { useSpeechInput } from './useSpeechInput';
import './MicButton.css';

interface MicButtonProps {
  onTranscript: (text: string) => void;
  onCommit: (text: string) => void;
}

export const MicButton = ({ onTranscript, onCommit }: MicButtonProps) => {
  const { lang, t } = useI18n();
  const {
    micOpen,
    setMicOpen,
    setAudioLevel,
    visible,
    capabilities,
    confirmVoice,
    setTranscript,
    setSttError,
    noteVoiceAsked
  } = useJarvis();

  const deliver = useCallback(
    (text: string) => {
      setTranscript({ text, final: true });
      if (confirmVoice) {
        onTranscript(text);
        setMicOpen(false);
        return;
      }
      onTranscript('');
      noteVoiceAsked();
      onCommit(text);
      setMicOpen(false);
    },
    [confirmVoice, onTranscript, onCommit, setMicOpen, setTranscript, noteVoiceAsked]
  );

  const recorder = useRecorder({ lang, onText: deliver });

  const speech = useSpeechInput({
    onInterim: (text) => setTranscript({ text, final: false }),
    onFinal: deliver,
    onFailure: (code) => {
      if (code === 'network' && recorder.supported && capabilities.stt === 'server') {
        setSttError(null);
        recorder.start();
        return;
      }
      setSttError(code === 'not-allowed' || code === 'service-not-allowed' ? 'not-allowed' : code);
      setMicOpen(false);
    }
  });

  const serverOnly = !speech.supported;
  const available =
    speech.supported || (recorder.supported && capabilities.stt === 'server');

  useMicLevel(micOpen, (level) => {
    setAudioLevel(level);
    speech.noteLevel(level);
  });

  const begin = useCallback(() => {
    if (!available || micOpen) {
      return;
    }
    setSttError(null);
    setTranscript({ text: '', final: false });
    setMicOpen(true);
    if (serverOnly) {
      recorder.start();
      return;
    }
    speech.start();
  }, [available, micOpen, serverOnly, setMicOpen, setSttError, setTranscript, recorder, speech]);

  const end = useCallback(() => {
    if (!micOpen) {
      return;
    }
    if (serverOnly || recorder.recording) {
      recorder.stop();
    } else {
      speech.stop();
    }
    setMicOpen(false);
  }, [micOpen, serverOnly, recorder, speech, setMicOpen]);

  useEffect(() => {
    if (!visible) {
      return;
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (isEditableTarget(event.target)) {
        return;
      }
      if (event.code === 'Space' && !event.repeat) {
        event.preventDefault();
        begin();
        return;
      }
      if (event.key === 'm' || event.key === 'M' || event.key === 'ь' || event.key === 'Ь') {
        event.preventDefault();
        if (micOpen) {
          end();
          return;
        }
        begin();
      }
    };
    const onKeyUp = (event: KeyboardEvent) => {
      if (event.code !== 'Space' || isEditableTarget(event.target)) {
        return;
      }
      event.preventDefault();
      end();
    };
    window.addEventListener('keydown', onKeyDown);
    window.addEventListener('keyup', onKeyUp);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('keyup', onKeyUp);
    };
  }, [visible, begin, end, micOpen]);

  return (
    <button
      type="button"
      className="jarvis-mic"
      data-open={micOpen ? 'true' : undefined}
      disabled={!available}
      aria-label={micOpen ? t('jarvis.micStop') : t('jarvis.micStart')}
      aria-pressed={micOpen}
      title={available ? t('jarvis.micHint') : t('jarvis.micUnavailable')}
      onClick={() => (micOpen ? end() : begin())}
    >
      <span className="jarvis-mic-dot" aria-hidden="true" />
    </button>
  );
};
