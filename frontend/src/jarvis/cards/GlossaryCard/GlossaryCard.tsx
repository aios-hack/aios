import { useT } from '@/shared/i18n/I18nContext';
import { readGlossary } from '@/jarvis/cards/payloads';
import { EmptyPayload } from '@/jarvis/cards/EmptyPayload/EmptyPayload';
import { routeAction, type ConsoleAction } from '@/jarvis/actions/lib/consoleAction';
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
          <span className="jarvis-glossary-label">{t('jarvis-cards.glossaryFormula')}</span>
          <code>{entry.formula}</code>
        </p>
      )}
      <p className="jarvis-glossary-meta">
        {entry.unit === null ? null : (
          <span>
            {t('jarvis-cards.glossaryUnit')}: {entry.unit}
          </span>
        )}
        {entry.source === null ? null : (
          <span>
            {t('jarvis-cards.glossarySource')}: {entry.source}
          </span>
        )}
      </p>
      {entry.where_in_platform.length === 0 ? null : (
        <div className="jarvis-glossary-where">
          <p className="jarvis-glossary-label">{t('jarvis-cards.glossaryWhere')}</p>
          <ul>
            {entry.where_in_platform.map((place) => (
              <li key={`${place.workspace}:${place.view}`}>
                <span>{place.what}</span>
                <button
                  type="button"
                  className="jarvis-glossary-open"
                  onClick={() => onOpen(routeAction(place.workspace, place.view, place.spotlight))}
                >
                  {t('jarvis-cards.open')}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
      {entry.related.length === 0 ? null : (
        <p className="jarvis-glossary-related">
          <span className="jarvis-glossary-label">{t('jarvis-cards.glossaryRelated')}</span>
          {entry.related.join(' · ')}
        </p>
      )}
    </div>
  );
};
