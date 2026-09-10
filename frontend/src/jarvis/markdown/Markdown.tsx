import { createElement, Fragment, type ReactNode } from 'react';
import { parseBlocks, type Block } from './blocks';
import { parseInline, type InlineSpan } from './inline';
import { CodeBlock } from './CodeBlock';
import './Markdown.css';

const renderSpans = (spans: InlineSpan[]): ReactNode =>
  spans.map((span, index) => {
    if (span.kind === 'text') {
      return <Fragment key={index}>{span.text}</Fragment>;
    }
    if (span.kind === 'code') {
      return (
        <code className="jarvis-md-inline-code" key={index}>
          {span.text}
        </code>
      );
    }
    if (span.kind === 'strong') {
      return <strong key={index}>{renderSpans(span.spans)}</strong>;
    }
    if (span.kind === 'emphasis') {
      return <em key={index}>{renderSpans(span.spans)}</em>;
    }
    return (
      <a
        className="jarvis-md-link"
        key={index}
        href={span.href}
        target="_blank"
        rel="noopener noreferrer"
      >
        {renderSpans(span.spans)}
      </a>
    );
  });

const renderText = (text: string): ReactNode => renderSpans(parseInline(text));

const renderBlock = (block: Block, key: number): ReactNode => {
  if (block.kind === 'heading') {
    return createElement(
      `h${Math.min(block.level + 2, 6)}`,
      { className: 'jarvis-md-heading', key, 'data-level': block.level },
      renderText(block.text)
    );
  }
  if (block.kind === 'paragraph') {
    return (
      <p className="jarvis-md-paragraph" key={key}>
        {renderText(block.text)}
      </p>
    );
  }
  if (block.kind === 'list') {
    const items = block.items.map((item, index) => (
      <li key={index}>{renderText(item)}</li>
    ));
    return block.ordered ? (
      <ol className="jarvis-md-list" key={key}>
        {items}
      </ol>
    ) : (
      <ul className="jarvis-md-list" key={key}>
        {items}
      </ul>
    );
  }
  if (block.kind === 'quote') {
    return (
      <blockquote className="jarvis-md-quote" key={key}>
        {renderText(block.text)}
      </blockquote>
    );
  }
  if (block.kind === 'rule') {
    return <hr className="jarvis-md-rule" key={key} />;
  }
  if (block.kind === 'table') {
    return (
      <div className="jarvis-md-table-scroll" key={key}>
        <table className="jarvis-md-table">
          <thead>
            <tr>
              {block.head.map((cell, index) => (
                <th key={index}>{renderText(cell)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {block.rows.map((row, rowIndex) => (
              <tr key={rowIndex}>
                {row.map((cell, index) => (
                  <td key={index}>{renderText(cell)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }
  return <CodeBlock key={key} lang={block.lang} code={block.code} />;
};

export const Markdown = ({ source }: { source: string }) => (
  <div className="jarvis-md">
    {parseBlocks(source).map((block, index) => renderBlock(block, index))}
  </div>
);
