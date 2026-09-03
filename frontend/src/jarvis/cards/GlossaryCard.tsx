import { useT } from '../../i18n/I18nContext';
import { readGlossary } from './cardPayloads';
import { EmptyPayload } from './EmptyPayload';
import { routeAction, type ConsoleAction } from '../actions/consoleAction';
import './GlossaryCard.css';

interface GlossaryCardProps {
  payload: unknown;
  onOpen: (action: ConsoleAction) => void;
}

export const GlossaryCard = ({ payload, onOpen }: GlossaryCardProps) => {
  const t = useT();
  const entry = readGlossary(payload);
  if (entry === null) {
    return <EmptyPayload />;
  }

  return (
    <div className="jarvis-glossary">
      <p className="jarvis-glossary-definition">{entry.definition}</p>
      {entry.formula === null ? null : (
        <p className="jarvis-glossary-formula">
          <span className="jarvis-glossary-label">{t('jarvis.glossaryFormula')}</span>
          <code>{entry.formula}</code>
        </p>
      )}
      <p className="jarvis-glossary-meta">
        {entry.unit === null ? null : (
          <span>
            {t('jarvis.glossaryUnit')}: {entry.unit}
          </span>
        )}
        {entry.source === null ? null : (
          <span>
            {t('jarvis.glossarySource')}: {entry.source}
          </span>
        )}
      </p>
      {entry.where_in_platform.length === 0 ? null : (
        <div className="jarvis-glossary-where">
          <p className="jarvis-glossary-label">{t('jarvis.glossaryWhere')}</p>
          <ul>
            {entry.where_in_platform.map((place) => (
              <li key={`${place.workspace}:${place.view}`}>
                <span>{place.what}</span>
                <button
                  type="button"
                  className="jarvis-glossary-open"
                  onClick={() => onOpen(routeAction(place.workspace, place.view, place.spotlight))}
                >
                  {t('jarvis.open')}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
      {entry.related.length === 0 ? null : (
        <p className="jarvis-glossary-related">
          <span className="jarvis-glossary-label">{t('jarvis.glossaryRelated')}</span>
          {entry.related.join(' · ')}
        </p>
      )}
    </div>
  );
};
