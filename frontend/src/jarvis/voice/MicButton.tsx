import { useCallback, useEffect } from 'react';
import { useT } from '../../i18n/I18nContext';
import { isEditableTarget } from '../../app/useHotkeys';
import { useJarvis } from '../JarvisContext';
import { useMicLevel } from './useMicLevel';
import { useSpeechInput } from './useSpeechInput';
import './MicButton.css';

interface MicButtonProps {
  onTranscript: (text: string) => void;
  onCommit: (text: string) => void;
}

export const MicButton = ({ onTranscript, onCommit }: MicButtonProps) => {
  const t = useT();
  const { micOpen, setMicOpen, setAudioLevel, visible } = useJarvis();

  const onFinal = useCallback(
    (text: string) => {
      onTranscript('');
      onCommit(text);
      setMicOpen(false);
    },
    [onTranscript, onCommit, setMicOpen]
  );

  const { supported, start, stop } = useSpeechInput({ onInterim: onTranscript, onFinal });
  useMicLevel(micOpen, setAudioLevel);

  const begin = useCallback(() => {
    if (!supported || micOpen) {
      return;
    }
    setMicOpen(true);
    start();
  }, [supported, micOpen, setMicOpen, start]);

  const end = useCallback(() => {
    if (!micOpen) {
      return;
    }
    stop();
    setMicOpen(false);
  }, [micOpen, stop, setMicOpen]);

  useEffect(() => {
    if (!supported || !visible) {
      return;
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.code !== 'Space' || event.repeat || isEditableTarget(event.target)) {
        return;
      }
      event.preventDefault();
      begin();
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
  }, [supported, visible, begin, end]);

  if (!supported) {
    return null;
  }

  return (
    <button
      type="button"
      className="jarvis-mic"
      data-open={micOpen ? 'true' : undefined}
      aria-label={micOpen ? t('jarvis.micStop') : t('jarvis.micStart')}
      aria-pressed={micOpen}
      title={t('jarvis.micHint')}
      onClick={() => (micOpen ? end() : begin())}
    >
      <span className="jarvis-mic-dot" aria-hidden="true" />
    </button>
  );
};
