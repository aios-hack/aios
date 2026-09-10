export type TokenKind = 'plain' | 'keyword' | 'string' | 'number' | 'comment' | 'key';

export interface CodeToken {
  kind: TokenKind;
  text: string;
}

export type CodeLanguage = 'python' | 'ts' | 'bash' | 'json' | 'yaml' | 'plain';

const KEYWORDS: Record<Exclude<CodeLanguage, 'plain' | 'json' | 'yaml'>, readonly string[]> = {
  python: [
    'def', 'class', 'return', 'import', 'from', 'as', 'if', 'elif', 'else', 'for', 'while',
    'in', 'not', 'and', 'or', 'with', 'try', 'except', 'finally', 'raise', 'yield', 'lambda',
    'None', 'True', 'False', 'async', 'await', 'pass', 'break', 'continue', 'global', 'assert'
  ],
  ts: [
    'const', 'let', 'var', 'function', 'return', 'import', 'export', 'from', 'as', 'if',
    'else', 'for', 'while', 'of', 'in', 'new', 'class', 'extends', 'interface', 'type',
    'async', 'await', 'try', 'catch', 'finally', 'throw', 'null', 'undefined', 'true',
    'false', 'this', 'default', 'switch', 'case', 'break', 'continue'
  ],
  bash: [
    'if', 'then', 'else', 'elif', 'fi', 'for', 'do', 'done', 'while', 'case', 'esac',
    'function', 'return', 'export', 'local', 'echo', 'cd', 'set', 'source', 'sudo'
  ]
};

const ALIASES: Record<string, CodeLanguage> = {
  py: 'python',
  python: 'python',
  python3: 'python',
  ts: 'ts',
  tsx: 'ts',
  typescript: 'ts',
  js: 'ts',
  jsx: 'ts',
  javascript: 'ts',
  sh: 'bash',
  bash: 'bash',
  shell: 'bash',
  zsh: 'bash',
  console: 'bash',
  json: 'json',
  yaml: 'yaml',
  yml: 'yaml'
};

export const languageOf = (raw: string): CodeLanguage =>
  ALIASES[raw.trim().toLowerCase()] ?? 'plain';

const COMMENT_PREFIX: Record<CodeLanguage, readonly string[]> = {
  python: ['#'],
  bash: ['#'],
  yaml: ['#'],
  ts: ['//'],
  json: [],
  plain: []
};

const isWordChar = (char: string): boolean => /[A-Za-z0-9_$]/.test(char);
const isDigit = (char: string): boolean => char >= '0' && char <= '9';

const push = (tokens: CodeToken[], kind: TokenKind, text: string): void => {
  if (text.length === 0) {
    return;
  }
  const last = tokens[tokens.length - 1];
  if (last !== undefined && last.kind === kind) {
    last.text += text;
    return;
  }
  tokens.push({ kind, text });
};

const readString = (line: string, start: number): number => {
  const quote = line[start];
  let index = start + 1;
  while (index < line.length) {
    if (line[index] === '\\') {
      index += 2;
      continue;
    }
    if (line[index] === quote) {
      return index + 1;
    }
    index += 1;
  }
  return line.length;
};

export const highlightLine = (line: string, lang: CodeLanguage): CodeToken[] => {
  if (lang === 'plain') {
    return line.length === 0 ? [] : [{ kind: 'plain', text: line }];
  }
  const tokens: CodeToken[] = [];
  const comments = COMMENT_PREFIX[lang];
  const keywords =
    lang === 'json' || lang === 'yaml' ? [] : (KEYWORDS[lang] as readonly string[]);
  let index = 0;
  while (index < line.length) {
    const rest = line.slice(index);
    const comment = comments.find((prefix) => rest.startsWith(prefix));
    if (comment !== undefined) {
      push(tokens, 'comment', rest);
      break;
    }
    const char = line[index];
    if (char === '"' || char === "'") {
      const end = readString(line, index);
      const text = line.slice(index, end);
      const after = line.slice(end).trimStart();
      const isKey = (lang === 'json' || lang === 'yaml') && after.startsWith(':');
      push(tokens, isKey ? 'key' : 'string', text);
      index = end;
      continue;
    }
    if (isDigit(char) && (index === 0 || !isWordChar(line[index - 1]))) {
      let end = index;
      while (end < line.length && /[0-9._]/.test(line[end])) {
        end += 1;
      }
      push(tokens, 'number', line.slice(index, end));
      index = end;
      continue;
    }
    if (isWordChar(char)) {
      let end = index;
      while (end < line.length && isWordChar(line[end])) {
        end += 1;
      }
      const word = line.slice(index, end);
      const after = line.slice(end).trimStart();
      if (lang === 'yaml' && after.startsWith(':') && line.slice(0, index).trim().length === 0) {
        push(tokens, 'key', word);
      } else if (keywords.includes(word)) {
        push(tokens, 'keyword', word);
      } else if (word === 'true' || word === 'false' || word === 'null') {
        push(tokens, 'keyword', word);
      } else {
        push(tokens, 'plain', word);
      }
      index = end;
      continue;
    }
    push(tokens, 'plain', char);
    index += 1;
  }
  return tokens;
};

export const highlight = (code: string, lang: CodeLanguage): CodeToken[][] =>
  code.split('\n').map((line) => highlightLine(line, lang));
