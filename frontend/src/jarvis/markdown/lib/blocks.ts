export interface HeadingBlock {
  kind: 'heading';
  level: number;
  text: string;
}

export interface ParagraphBlock {
  kind: 'paragraph';
  text: string;
}

export interface ListBlock {
  kind: 'list';
  ordered: boolean;
  items: string[];
}

export interface CodeBlock {
  kind: 'code';
  lang: string;
  code: string;
  closed: boolean;
}

export interface QuoteBlock {
  kind: 'quote';
  text: string;
}

export interface TableBlock {
  kind: 'table';
  head: string[];
  rows: string[][];
}

export interface RuleBlock {
  kind: 'rule';
}

export type Block =
  | HeadingBlock
  | ParagraphBlock
  | ListBlock
  | CodeBlock
  | QuoteBlock
  | TableBlock
  | RuleBlock;

const FENCE = /^\s{0,3}(`{3,}|~{3,})\s*([\w+-]*)\s*$/;
const HEADING = /^\s{0,3}(#{1,6})\s+(.*)$/;
const BULLET = /^\s{0,3}[-*+]\s+(.*)$/;
const ORDERED = /^\s{0,3}\d{1,9}[.)]\s+(.*)$/;
const QUOTE = /^\s{0,3}>\s?(.*)$/;
const RULE = /^\s{0,3}([-*_])(\s*\1){2,}\s*$/;
const DIVIDER = /^\s{0,3}\|?[\s:|-]+\|[\s:|-]*$/;

const splitRow = (line: string): string[] => {
  const trimmed = line.trim().replace(/^\|/, '').replace(/\|$/, '');
  return trimmed.split('|').map((cell) => cell.trim());
};

const isTableRow = (line: string): boolean => line.includes('|') && line.trim().length > 0;

export const parseBlocks = (source: string): Block[] => {
  const lines = source.replace(/\r\n/g, '\n').split('\n');
  const blocks: Block[] = [];
  let index = 0;

  const flushParagraph = (buffer: string[]): void => {
    const text = buffer.join('\n').trim();
    if (text.length > 0) {
      blocks.push({ kind: 'paragraph', text });
    }
  };

  while (index < lines.length) {
    const line = lines[index];
    const fence = FENCE.exec(line);
    if (fence !== null) {
      const marker = fence[1][0];
      const width = fence[1].length;
      const code: string[] = [];
      let closed = false;
      index += 1;
      while (index < lines.length) {
        const closing = FENCE.exec(lines[index]);
        if (closing !== null && closing[1][0] === marker && closing[1].length >= width) {
          closed = true;
          index += 1;
          break;
        }
        code.push(lines[index]);
        index += 1;
      }
      blocks.push({ kind: 'code', lang: fence[2], code: code.join('\n'), closed });
      continue;
    }
    if (line.trim().length === 0) {
      index += 1;
      continue;
    }
    if (RULE.test(line)) {
      blocks.push({ kind: 'rule' });
      index += 1;
      continue;
    }
    const heading = HEADING.exec(line);
    if (heading !== null) {
      blocks.push({ kind: 'heading', level: heading[1].length, text: heading[2].trim() });
      index += 1;
      continue;
    }
    const quote = QUOTE.exec(line);
    if (quote !== null) {
      const buffer: string[] = [quote[1]];
      index += 1;
      while (index < lines.length) {
        const next = QUOTE.exec(lines[index]);
        if (next === null) {
          break;
        }
        buffer.push(next[1]);
        index += 1;
      }
      blocks.push({ kind: 'quote', text: buffer.join('\n').trim() });
      continue;
    }
    if (
      isTableRow(line) &&
      index + 1 < lines.length &&
      DIVIDER.test(lines[index + 1]) &&
      lines[index + 1].includes('|')
    ) {
      const head = splitRow(line);
      index += 2;
      const rows: string[][] = [];
      while (index < lines.length && isTableRow(lines[index])) {
        rows.push(splitRow(lines[index]));
        index += 1;
      }
      blocks.push({ kind: 'table', head, rows });
      continue;
    }
    const bullet = BULLET.exec(line);
    const ordered = ORDERED.exec(line);
    if (bullet !== null || ordered !== null) {
      const isOrdered = ordered !== null;
      const items: string[] = [];
      while (index < lines.length) {
        const current = isOrdered ? ORDERED.exec(lines[index]) : BULLET.exec(lines[index]);
        if (current === null) {
          break;
        }
        items.push(current[1].trim());
        index += 1;
      }
      blocks.push({ kind: 'list', ordered: isOrdered, items });
      continue;
    }
    const buffer: string[] = [];
    while (index < lines.length) {
      const current = lines[index];
      if (
        current.trim().length === 0 ||
        FENCE.test(current) ||
        HEADING.test(current) ||
        QUOTE.test(current) ||
        RULE.test(current) ||
        BULLET.test(current) ||
        ORDERED.test(current)
      ) {
        break;
      }
      buffer.push(current);
      index += 1;
    }
    flushParagraph(buffer);
  }
  return blocks;
};
