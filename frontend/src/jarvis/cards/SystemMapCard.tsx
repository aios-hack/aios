import { useState } from 'react';
import { useI18n } from '../../i18n/I18nContext';
import { routeAction, type ConsoleAction } from '../actions/consoleAction';
import { readSystemMap } from './cardPayloads';
import { EmptyPayload } from './EmptyPayload';
import { VIEW_H, VIEW_W, edgeLine, placeNodes } from './systemMapLayout';
import './SystemMapCard.css';

interface SystemMapCardProps {
  payload: unknown;
  onOpen: (action: ConsoleAction) => void;
}

const routeOf = (route: string | null): ConsoleAction | null => {
  if (route === null) {
    return null;
  }
  const [workspace, view] = route.split('/');
  const action = routeAction(workspace ?? '', view ?? '', null);
  return action.view === undefined ? null : action;
};

export const SystemMapCard = ({ payload, onOpen }: SystemMapCardProps) => {
  const { lang, t } = useI18n();
  const map = readSystemMap(payload, lang);
  const [picked, setPicked] = useState<string | null>(null);
  if (map === null) {
    return <EmptyPayload />;
  }
  const places = placeNodes(map.nodes);
  const selected = picked ?? map.focus;
  const node = map.nodes.find((entry) => entry.id === selected) ?? null;
  const action = node === null ? null : routeOf(node.route);

  return (
    <div className="jarvis-map">
      <svg
        className="jarvis-map-svg"
        viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
        role="group"
        aria-label={t('jarvis.mapLabel')}
      >
        {map.edges.map((edge, index) => {
          const line = edgeLine(places, edge);
          if (line === null) {
            return null;
          }
          const touched = selected === edge.from || selected === edge.to;
          return (
            <line
              className="jarvis-map-edge"
              key={`${edge.from}-${edge.to}-${index}`}
              data-on={touched ? 'true' : undefined}
              x1={line.x1}
              y1={line.y1}
              x2={line.x2}
              y2={line.y2}
            />
          );
        })}
        {places.map((place) => {
          const entry = map.nodes.find((item) => item.id === place.id);
          if (entry === undefined) {
            return null;
          }
          const on = entry.id === selected;
          return (
            <g
              className="jarvis-map-node"
              key={entry.id}
              data-kind={entry.kind}
              data-on={on ? 'true' : undefined}
              transform={`translate(${place.x} ${place.y})`}
              tabIndex={0}
              role="button"
              aria-label={entry.label}
              aria-pressed={on}
              onClick={() => setPicked(entry.id)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault();
                  setPicked(entry.id);
                }
              }}
            >
              <circle className="jarvis-map-dot" r={on ? 3.4 : 2.2} />
              <text className="jarvis-map-text" y={-4.4}>
                {entry.label}
              </text>
            </g>
          );
        })}
      </svg>
      <p className="jarvis-map-count">
        {t('jarvis.mapCount', {
          nodes: String(map.total_nodes),
          edges: String(map.total_edges)
        })}
      </p>
      {node === null ? null : (
        <div className="jarvis-map-detail">
          <p className="jarvis-map-detail-title">{node.label}</p>
          <p className="jarvis-map-detail-kind">{node.kind}</p>
          <p className="jarvis-map-detail-summary">{node.summary}</p>
          {node.files.length === 0 ? null : (
            <p className="jarvis-map-detail-files">{node.files.join(' · ')}</p>
          )}
          <div className="jarvis-map-detail-actions">
            {action === null ? null : (
              <button
                type="button"
                className="jarvis-map-action"
                onClick={() => onOpen(action)}
              >
                {t('jarvis.openInConsole')}
              </button>
            )}
            {node.doc === null ? null : (
              <span className="jarvis-map-doc">{node.doc}</span>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
