export interface TextSpan {
  kind: 'text';
  text: string;
}

export interface StrongSpan {
  kind: 'strong';
  spans: InlineSpan[];
}

export interface EmphasisSpan {
  kind: 'emphasis';
  spans: InlineSpan[];
}

export interface CodeSpan {
  kind: 'code';
  text: string;
}

export interface LinkSpan {
  kind: 'link';
  href: string;
  spans: InlineSpan[];
}

export type InlineSpan = TextSpan | StrongSpan | EmphasisSpan | CodeSpan | LinkSpan;

const LINK = /^\[([^\]]*)\]\((https?:\/\/[^\s)]+)\)/;
const STRONG = /^(\*\*|__)([\s\S]+?)\1/;
const EMPHASIS = /^(\*|_)([^*_\n][\s\S]*?)\1/;
const CODE = /^(`+)([\s\S]*?)\1/;

const pushText = (spans: InlineSpan[], text: string): void => {
  if (text.length === 0) {
    return;
  }
  const last = spans[spans.length - 1];
  if (last !== undefined && last.kind === 'text') {
    last.text += text;
    return;
  }
  spans.push({ kind: 'text', text });
};

export const parseInline = (source: string): InlineSpan[] => {
  const spans: InlineSpan[] = [];
  let rest = source;
  while (rest.length > 0) {
    const char = rest[0];
    if (char === '\\' && rest.length > 1) {
      pushText(spans, rest[1]);
      rest = rest.slice(2);
      continue;
    }
    if (char === '`') {
      const code = CODE.exec(rest);
      if (code !== null) {
        spans.push({ kind: 'code', text: code[2].trim() });
        rest = rest.slice(code[0].length);
        continue;
      }
    }
    if (char === '[') {
      const link = LINK.exec(rest);
      if (link !== null) {
        spans.push({ kind: 'link', href: link[2], spans: parseInline(link[1]) });
        rest = rest.slice(link[0].length);
        continue;
      }
    }
    if (char === '*' || char === '_') {
      const strong = STRONG.exec(rest);
      if (strong !== null) {
        spans.push({ kind: 'strong', spans: parseInline(strong[2]) });
        rest = rest.slice(strong[0].length);
        continue;
      }
      const emphasis = EMPHASIS.exec(rest);
      if (emphasis !== null) {
        spans.push({ kind: 'emphasis', spans: parseInline(emphasis[2]) });
        rest = rest.slice(emphasis[0].length);
        continue;
      }
    }
    pushText(spans, char);
    rest = rest.slice(1);
  }
  return spans;
};
