import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { useT } from '../../i18n/I18nContext';
import { QUESTION_LIMIT } from '../transport/JarvisTransport';
import { MicButton } from '../voice/MicButton';
import './InputDock.css';

interface InputDockProps {
  onAsk: (question: string) => void;
  focusSignal: number;
  history: readonly string[];
}

export const recallAt = (
  history: readonly string[],
  cursor: number
): { text: string; cursor: number } => {
  if (history.length === 0) {
    return { text: '', cursor: -1 };
  }
  const next = Math.min(cursor + 1, history.length - 1);
  return { text: history[history.length - 1 - next], cursor: next };
};

export const InputDock = ({ onAsk, focusSignal, history }: InputDockProps) => {
  const t = useT();
  const [text, setText] = useState('');
  const [cursor, setCursor] = useState(-1);
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
    setCursor(-1);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      submit();
      return;
    }
    if (event.key === 'ArrowUp' && (text.length === 0 || cursor >= 0)) {
      const recalled = recallAt(history, cursor);
      if (recalled.cursor < 0) {
        return;
      }
      event.preventDefault();
      setText(recalled.text);
      setCursor(recalled.cursor);
      return;
    }
    if (event.key === 'ArrowDown' && cursor >= 0) {
      event.preventDefault();
      const next = cursor - 1;
      setCursor(next);
      setText(next < 0 ? '' : history[history.length - 1 - next]);
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
        onChange={(event) => {
          setText(event.target.value.slice(0, QUESTION_LIMIT));
          setCursor(-1);
        }}
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
