import { useCallback, useEffect, useRef, useState, type CSSProperties, type KeyboardEvent } from 'react';
import { useI18n } from '../../i18n/I18nContext';
import type { Scene } from '../scenes';
import { beadTime, cropQuestion, glyphsOf } from './cardGlyphs';
import { HistorySessions } from './HistorySessions';
import { HistoryThread } from './HistoryThread';
import './HistoryRail.css';

interface HistoryRailProps {
  scenes: readonly Scene[];
  activeIndex: number;
  onSelect: (index: number) => void;
}

export const HistoryRail = ({ scenes, activeIndex, onSelect }: HistoryRailProps) => {
  const { lang, t } = useI18n();
  const [hover, setHover] = useState<number | null>(null);
  const listRef = useRef<HTMLOListElement>(null);
  const beads = scenes
    .map((scene, index) => ({ scene, index }))
    .filter((entry) => entry.scene.question.trim().length > 0);
  const count = beads.length;

  useEffect(() => {
    const node = listRef.current?.querySelector<HTMLElement>('[data-active="true"]');
    node?.scrollIntoView({ block: 'nearest', inline: 'center' });
  }, [activeIndex, count]);

  const onWheel = useCallback((event: WheelEvent) => {
    const node = listRef.current;
    if (node === null) {
      return;
    }
    const delta = Math.abs(event.deltaX) > Math.abs(event.deltaY) ? event.deltaX : event.deltaY;
    node.scrollLeft += delta;
  }, []);

  useEffect(() => {
    const node = listRef.current;
    if (node === null) {
      return;
    }
    node.addEventListener('wheel', onWheel, { passive: true });
    return () => node.removeEventListener('wheel', onWheel);
  }, [onWheel]);

  const step = (delta: number) => {
    const at = beads.findIndex((entry) => entry.index === activeIndex);
    const next = beads[(at < 0 ? 0 : at) + delta];
    if (next !== undefined) {
      onSelect(next.index);
    }
  };

  const onKeyDown = (event: KeyboardEvent<HTMLOListElement>) => {
    if (event.key === 'ArrowRight') {
      event.preventDefault();
      step(1);
      return;
    }
    if (event.key === 'ArrowLeft') {
      event.preventDefault();
      step(-1);
      return;
    }
    if (event.key === 'Home') {
      event.preventDefault();
      if (beads[0] !== undefined) {
        onSelect(beads[0].index);
      }
      return;
    }
    if (event.key === 'End') {
      event.preventDefault();
      const last = beads[count - 1];
      if (last !== undefined) {
        onSelect(last.index);
      }
    }
  };

  return (
    <div className="jarvis-rail" data-empty={count === 0 ? 'true' : undefined}>
      <ol
        className="jarvis-rail-beads"
        ref={listRef}
        role="listbox"
        tabIndex={0}
        aria-label={t('jarvis.railLabel')}
        aria-activedescendant={
          beads.some((entry) => entry.index === activeIndex)
            ? `jarvis-bead-${activeIndex}`
            : undefined
        }
        onKeyDown={onKeyDown}
      >
        <HistoryThread count={count} />
        {beads.map(({ scene, index }) => {
          const active = index === activeIndex;
          const glyphs = glyphsOf(scene.cards.map((entry) => entry.card.type));
          const caption = (scene.caption ?? scene.captionDraft).split('\n')[0];
          return (
            <li
              className="jarvis-rail-bead"
              key={scene.id}
              id={`jarvis-bead-${index}`}
              role="option"
              aria-selected={active}
              data-active={active ? 'true' : undefined}
              onPointerEnter={() => setHover(index)}
              onPointerLeave={() => setHover((value) => (value === index ? null : value))}
            >
              <button
                type="button"
                className="jarvis-rail-button"
                tabIndex={-1}
                aria-label={t('jarvis.railBead', { question: scene.question })}
                onClick={() => onSelect(index)}
                onFocus={() => setHover(index)}
                onBlur={() => setHover((value) => (value === index ? null : value))}
              >
                <span className="jarvis-rail-dot" aria-hidden="true">
                  {glyphs.map((glyph, position) => (
                    <span
                      className="jarvis-rail-glyph"
                      key={`${glyph}-${position}`}
                      style={{ '--glyph-index': `${position}` } as CSSProperties}
                    >
                      {glyph}
                    </span>
                  ))}
                </span>
                <span className="jarvis-rail-question">{cropQuestion(scene.question)}</span>
                <span className="jarvis-rail-time">{beadTime(lang, scene.ts)}</span>
              </button>
              {hover === index ? (
                <span className="jarvis-rail-preview" role="presentation">
                  <span className="jarvis-rail-preview-question">{scene.question}</span>
                  <span className="jarvis-rail-preview-glyphs" aria-hidden="true">
                    {glyphs.length === 0 ? t('jarvis.railNoCards') : glyphs.join(' ')}
                  </span>
                  {caption.length === 0 ? null : (
                    <span className="jarvis-rail-preview-caption">{caption}</span>
                  )}
                </span>
              ) : null}
            </li>
          );
        })}
      </ol>
      <HistorySessions />
    </div>
  );
};
