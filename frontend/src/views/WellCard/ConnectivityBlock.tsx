import { useT } from '../../i18n/I18nContext';
import { formatWindowDate, roundWeight } from '../shared/graphModel';
import type { WellConnectivity } from './neighbours';
import './ConnectivityBlock.css';

interface ConnectivityBlockProps {
  connectivity: WellConnectivity;
  onSelect: (well: string) => void;
}

export const ConnectivityBlock = ({ connectivity, onSelect }: ConnectivityBlockProps) => {
  const t = useT();
  const { group, inGraph, neighbours, threshold, window } = connectivity;

  return (
    <div className="wellcard-connectivity" data-testid="wellcard-connectivity">
      <p className="wellcard-group" data-testid="wellcard-group">
        <span className="wellcard-param-label">{t('wellcard.group.label')}</span>
        <span className="wellcard-group-value" data-group={group ?? ''}>
          {group ?? t('wellcard.group.none')}
        </span>
      </p>
      <p className="wellcard-window" data-testid="wellcard-window">
        <span className="wellcard-window-badge">
          {t('wellcard.neighbours.window', {
            start: formatWindowDate(window.start),
            end: formatWindowDate(window.end)
          })}
        </span>
        <span className="wellcard-window-note">{t('wellcard.neighbours.windowNote')}</span>
      </p>
      {!inGraph && (
        <p className="wellcard-empty">{t('wellcard.neighbours.absent')}</p>
      )}
      {inGraph && neighbours.length === 0 && (
        <p className="wellcard-empty">
          {t('wellcard.neighbours.empty', { threshold: roundWeight(threshold) })}
        </p>
      )}
      {neighbours.length > 0 && (
        <ul className="wellcard-neighbours" data-testid="wellcard-neighbours">
          {neighbours.map((neighbour) => (
            <li key={neighbour.well} className="wellcard-neighbour">
              <button
                type="button"
                className="wellcard-neighbour-button"
                data-neighbour={neighbour.well}
                data-role={neighbour.role}
                onClick={() => onSelect(neighbour.well)}
              >
                <span className="wellcard-neighbour-well">{neighbour.well}</span>
                <span className="wellcard-neighbour-role">
                  {t(
                    neighbour.role === 'INJ'
                      ? 'wellcard.neighbours.injector'
                      : 'wellcard.neighbours.producer'
                  )}
                </span>
                <span className="wellcard-neighbour-weight">
                  {roundWeight(neighbour.weight)}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};
