import { useCallback, useEffect, useState } from 'react';
import { useT } from '../../i18n/I18nContext';
import { highlight, languageOf } from './highlight';

const COPIED_MS = 1600;

interface CodeBlockProps {
  lang: string;
  code: string;
}

export const CodeBlock = ({ lang, code }: CodeBlockProps) => {
  const t = useT();
  const [copied, setCopied] = useState(false);
  const language = languageOf(lang);
  const lines = highlight(code, language);

  useEffect(() => {
    if (!copied) {
      return;
    }
    const id = window.setTimeout(() => setCopied(false), COPIED_MS);
    return () => window.clearTimeout(id);
  }, [copied]);

  const onCopy = useCallback(() => {
    const write = navigator.clipboard?.writeText;
    if (typeof write !== 'function') {
      return;
    }
    void navigator.clipboard.writeText(code).then(
      () => setCopied(true),
      () => setCopied(false)
    );
  }, [code]);

  return (
    <figure className="jarvis-md-code">
      <figcaption className="jarvis-md-code-head">
        <span className="jarvis-md-code-lang">
          {lang.trim().length === 0 ? t('jarvis.codePlain') : lang.trim()}
        </span>
        <button
          type="button"
          className="jarvis-md-code-copy"
          onClick={onCopy}
          data-copied={copied ? 'true' : undefined}
        >
          {copied ? t('jarvis.copied') : t('jarvis.copy')}
        </button>
      </figcaption>
      <pre className="jarvis-md-code-body">
        <code>
          {lines.map((tokens, line) => (
            <span className="jarvis-md-code-line" key={line}>
              {tokens.map((token, position) => (
                <span data-token={token.kind} key={position}>
                  {token.text}
                </span>
              ))}
              {'\n'}
            </span>
          ))}
        </code>
      </pre>
    </figure>
  );
};
