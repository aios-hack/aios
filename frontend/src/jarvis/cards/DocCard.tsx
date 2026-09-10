import { useState } from 'react';
import { useT } from '../../i18n/I18nContext';
import { Markdown } from '../markdown/Markdown';
import { readDoc } from './cardPayloads';
import { EmptyPayload } from './EmptyPayload';
import { highlightTerms } from './docHighlight';
import type { DocHit } from './payloadTypes';
import './DocCard.css';

const HitSnippet = ({ snippet, terms }: { snippet: string; terms: readonly string[] }) => (
  <p className="jarvis-doc-snippet">
    {highlightTerms(snippet, terms).map((part, index) =>
      part.match ? (
        <mark className="jarvis-doc-mark" key={index}>
          {part.text}
        </mark>
      ) : (
        <span key={index}>{part.text}</span>
      )
    )}
  </p>
);

export const DocCard = ({ payload }: { payload: unknown }) => {
  const t = useT();
  const [open, setOpen] = useState<DocHit | null>(null);
  const doc = readDoc(payload);
  if (doc === null) {
    return <EmptyPayload />;
  }

  return (
    <div className="jarvis-doc">
      <p className="jarvis-doc-index">
        {t('jarvis.docIndex', {
          chunks: String(doc.indexed_chunks),
          files: String(doc.indexed_files)
        })}
      </p>
      <ol className="jarvis-doc-hits">
        {doc.hits.map((hit, index) => (
          <li className="jarvis-doc-hit" key={`${hit.source}-${hit.anchor ?? index}`}>
            <p className="jarvis-doc-source">
              <span className="jarvis-doc-file">{hit.source}</span>
              {hit.score === null ? null : (
                <span className="jarvis-doc-score">{hit.score.toFixed(2)}</span>
              )}
            </p>
            {hit.heading.length === 0 ? null : (
              <p className="jarvis-doc-heading">{hit.heading}</p>
            )}
            <HitSnippet snippet={hit.snippet} terms={doc.terms} />
            {hit.text.length === 0 ? null : (
              <button
                type="button"
                className="jarvis-doc-open"
                onClick={() => setOpen(hit)}
              >
                {t('jarvis.docShowSection')}
              </button>
            )}
          </li>
        ))}
      </ol>
      {open === null ? null : (
        <div className="jarvis-doc-modal" role="dialog" aria-label={open.source}>
          <header className="jarvis-doc-modal-head">
            <p className="jarvis-doc-modal-title">
              {open.source}
              {open.heading.length === 0 ? '' : ` › ${open.heading}`}
            </p>
            <button
              type="button"
              className="jarvis-doc-modal-close"
              aria-label={t('jarvis.docClose')}
              onClick={() => setOpen(null)}
            >
              ×
            </button>
          </header>
          <div className="jarvis-doc-modal-body">
            <Markdown source={open.text} />
          </div>
        </div>
      )}
    </div>
  );
};
