import { useMemo } from 'react';
import { useDataset } from '../../data';
import { useT } from '../../i18n/I18nContext';
import { FIELD_SIZE, projectNodes } from '../../views/FieldProjection/model';
import { readFieldMap } from './cardPayloads';
import { EmptyPayload } from './EmptyPayload';
import './FieldMapCard.css';

const VIEW = FIELD_SIZE;

export const edgeOpacity = (weight: number, peak: number): number =>
  peak <= 0 ? 0.2 : Math.min(1, 0.18 + (Math.abs(weight) / peak) * 0.72);

export const FieldMapCard = ({ payload }: { payload: unknown }) => {
  const t = useT();
  const wells = useDataset('wells');
  const graph = useDataset('graph');
  const map = readFieldMap(payload);

  const positions = useMemo(() => {
    if (wells.status !== 'ready' || graph.status !== 'ready') {
      return new Map<string, { x: number; y: number }>();
    }
    const nodes = projectNodes(wells.data, graph.data);
    const placed = new Map<string, { x: number; y: number }>();
    for (const node of nodes) {
      const point = node.map ?? node.graph;
      if (point !== null) {
        placed.set(node.id, { x: point.x, y: point.y });
      }
    }
    return placed;
  }, [wells, graph]);

  if (map === null) {
    return <EmptyPayload />;
  }
  const peak = map.edges.reduce((top, edge) => Math.max(top, Math.abs(edge.weight)), 0);
  const focus = new Set(map.focus);
  const highlight = new Set(map.highlight);

  return (
    <div className="jarvis-map">
      <svg
        className="jarvis-map-plot"
        viewBox={`0 0 ${VIEW} ${VIEW}`}
        role="img"
        aria-label={`${t('jarvis.mapFocus')} ${map.focus.join(', ')}`}
      >
        {map.edges.map((edge) => {
          const from = positions.get(edge.injector);
          const to = positions.get(edge.producer);
          if (from === undefined || to === undefined) {
            return null;
          }
          return (
            <line
              key={`${edge.injector}-${edge.producer}`}
              className="jarvis-map-edge"
              x1={from.x}
              y1={from.y}
              x2={to.x}
              y2={to.y}
              opacity={edgeOpacity(edge.weight, peak)}
            />
          );
        })}
        {[...positions.entries()].map(([id, point]) => (
          <circle
            key={id}
            className="jarvis-map-node"
            cx={point.x}
            cy={point.y}
            r={focus.has(id) ? 2.6 : 1.4}
            data-role={focus.has(id) ? 'focus' : highlight.has(id) ? 'highlight' : 'dim'}
          />
        ))}
      </svg>
      <p className="jarvis-map-meta">
        <span>
          {t('jarvis.mapFocus')}: {map.focus.join(', ')}
        </span>
        <span>
          {t('jarvis.mapEdges')}: {map.edges.length}
        </span>
      </p>
    </div>
  );
};
