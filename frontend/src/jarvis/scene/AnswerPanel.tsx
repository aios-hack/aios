import { CaretRightIcon } from '@phosphor-icons/react';
import { useEffect, useId, useState } from 'react';
import { useT } from '../../i18n/I18nContext';
import { Markdown } from '../markdown/Markdown';
import type { Scene } from '../scenes';
import './AnswerPanel.css';

export const firstLineOf = (source: string): string => {
  for (const line of source.split('\n')) {
    const text = line.replace(/^[#>\s*_-]+/, '').trim();
    if (text.length > 0) {
      return text;
    }
  }
  return '';
};

export const AnswerPanel = ({ scene }: { scene: Scene | null }) => {
  const t = useT();
  const [expanded, setExpanded] = useState(false);
  const bodyId = useId();
  const source = scene?.answer ?? scene?.answerDraft ?? '';
  const sceneId = scene?.id ?? null;

  useEffect(() => {
    setExpanded(false);
  }, [sceneId]);

  useEffect(() => {
    if (source.length === 0) {
      return;
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.target instanceof HTMLTextAreaElement || event.target instanceof HTMLInputElement) {
        return;
      }
      if (event.key === 'a' || event.key === 'A' || event.key === 'ф' || event.key === 'Ф') {
        event.preventDefault();
        setExpanded((value) => !value);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [source.length]);

  if (source.trim().length === 0) {
    return null;
  }

  return (
    <section className="jarvis-answer" data-expanded={expanded ? 'true' : undefined}>
      <button
        type="button"
        className="jarvis-answer-toggle"
        aria-expanded={expanded}
        aria-controls={bodyId}
        onClick={() => setExpanded((value) => !value)}
      >
        <CaretRightIcon size={14} weight="bold" aria-hidden="true" />
        <span className="jarvis-answer-lead">
          {expanded ? t('jarvis.answerLabel') : firstLineOf(source)}
        </span>
        <kbd className="jarvis-answer-key">A</kbd>
      </button>
      <div className="jarvis-answer-body" id={bodyId} hidden={!expanded}>
        <Markdown source={source} />
      </div>
    </section>
  );
};
