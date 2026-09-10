import type { CardType } from '../transport/events';

const GLYPHS: Record<CardType, string> = {
  metric: '◆',
  well: '●',
  'well-list': '≡',
  'field-map': '◈',
  series: '∿',
  rule: '§',
  compare: '⇄',
  'event-strip': '⋮',
  pattern: '⚠',
  error: '×',
  glossary: 'A',
  guide: '☰',
  doc: '¶',
  'system-map': '⌘',
  'status-board': '◫',
  'run-list': '⋯',
  run: '▶',
  constraints: '⌗',
  council: '⚖',
  physics: 'Ω'
};

export const GLYPH_LIMIT = 4;

export const glyphOf = (type: CardType): string => GLYPHS[type] ?? '·';

export const glyphsOf = (types: readonly CardType[]): string[] =>
  types.slice(0, GLYPH_LIMIT).map(glyphOf);

export const QUESTION_CROP = 28;

export const cropQuestion = (question: string): string => {
  const text = question.trim();
  if (text.length <= QUESTION_CROP) {
    return text;
  }
  return `${text.slice(0, QUESTION_CROP - 1).trimEnd()}…`;
};

export const beadTime = (lang: string, ts: string | null): string => {
  if (ts === null || ts.length === 0) {
    return '';
  }
  const moment = new Date(ts);
  if (Number.isNaN(moment.getTime())) {
    return '';
  }
  return new Intl.DateTimeFormat(lang === 'en' ? 'en-GB' : 'ru-RU', {
    hour: '2-digit',
    minute: '2-digit'
  }).format(moment);
};

export const sessionDayKey = (lang: string, iso: string, today: Date): string => {
  const moment = new Date(iso);
  if (Number.isNaN(moment.getTime())) {
    return '';
  }
  const days = Math.floor(
    (Date.UTC(today.getFullYear(), today.getMonth(), today.getDate()) -
      Date.UTC(moment.getFullYear(), moment.getMonth(), moment.getDate())) /
      86400000
  );
  if (days === 0) {
    return 'today';
  }
  if (days === 1) {
    return 'yesterday';
  }
  return new Intl.DateTimeFormat(lang === 'en' ? 'en-GB' : 'ru-RU', {
    day: '2-digit',
    month: '2-digit'
  }).format(moment);
};
