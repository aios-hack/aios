import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { useT } from '../../i18n/I18nContext';
import { QUESTION_LIMIT } from '../transport/JarvisTransport';
import { MicButton } from '../voice/MicButton';
import './InputDock.css';

interface InputDockProps {
  onAsk: (question: string) => void;
  focusSignal: number;
}

export const InputDock = ({ onAsk, focusSignal }: InputDockProps) => {
  const t = useT();
  const [text, setText] = useState('');
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (focusSignal > 0) {
      ref.current?.focus();
    }
  }, [focusSignal]);

  const submit = () => {
    const trimmed = text.trim();
    if (trimmed.length === 0) {
      return;
    }
    onAsk(trimmed);
    setText('');
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  };

  return (
    <form
      className="jarvis-dock"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <textarea
        ref={ref}
        className="jarvis-dock-input"
        rows={1}
        aria-label={t('jarvis.inputLabel')}
        placeholder={t('jarvis.inputPlaceholder')}
        maxLength={QUESTION_LIMIT}
        value={text}
        onChange={(event) => setText(event.target.value.slice(0, QUESTION_LIMIT))}
        onKeyDown={onKeyDown}
      />
      <span className="jarvis-dock-count" aria-hidden="true">
        {t('jarvis.limit', { count: text.length })}
      </span>
      <MicButton onTranscript={(value) => setText(value)} onCommit={onAsk} />
      <button type="submit" className="jarvis-dock-send" disabled={text.trim().length === 0}>
        {t('jarvis.send')}
      </button>
    </form>
  );
};
