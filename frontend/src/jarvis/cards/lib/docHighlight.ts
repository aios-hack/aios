export interface HighlightPart {
  text: string;
  match: boolean;
}

const MIN_TERM = 3;

const stems = (terms: readonly string[]): string[] => {
  const collected: string[] = [];
  for (const term of terms) {
    const cleaned = term.trim().toLowerCase();
    if (cleaned.length < MIN_TERM) {
      continue;
    }
    const stem = cleaned.length > 5 ? cleaned.slice(0, cleaned.length - 2) : cleaned;
    if (!collected.includes(stem)) {
      collected.push(stem);
    }
  }
  return collected;
};

const isWordChar = (value: string): boolean => /[\p{L}\p{N}_]/u.test(value);

export const highlightTerms = (
  source: string,
  terms: readonly string[]
): HighlightPart[] => {
  const wanted = stems(terms);
  if (wanted.length === 0 || source.length === 0) {
    return [{ text: source, match: false }];
  }
  const parts: HighlightPart[] = [];
  let plain = '';
  let index = 0;
  while (index < source.length) {
    if (index > 0 && isWordChar(source[index - 1])) {
      plain += source[index];
      index += 1;
      continue;
    }
    let hit = 0;
    const lower = source.slice(index, index + 40).toLowerCase();
    for (const stem of wanted) {
      if (lower.startsWith(stem) && stem.length > hit) {
        hit = stem.length;
      }
    }
    if (hit === 0) {
      plain += source[index];
      index += 1;
      continue;
    }
    let end = index + hit;
    while (end < source.length && isWordChar(source[end])) {
      end += 1;
    }
    if (plain.length > 0) {
      parts.push({ text: plain, match: false });
      plain = '';
    }
    parts.push({ text: source.slice(index, end), match: true });
    index = end;
  }
  if (plain.length > 0) {
    parts.push({ text: plain, match: false });
  }
  return parts;
};
