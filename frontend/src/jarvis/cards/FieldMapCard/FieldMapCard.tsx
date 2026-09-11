import { useMemo } from 'react';
import { useScenarioDataset } from '@/entities';
import { useOptionalScenario } from '@/entities/scenarios/model/ScenarioContext';
import { useT } from '@/shared/i18n/I18nContext';
import { FIELD_SIZE, projectNodes } from '@/entities/graph/model/projection';
import { readFieldMap } from '@/jarvis/cards/payloads';
import { EmptyPayload } from '@/jarvis/cards/EmptyPayload/EmptyPayload';
import './FieldMapCard.css';

const VIEW = FIELD_SIZE;

export const edgeOpacity = (weight: number, peak: number): number =>
  peak <= 0 ? 0.2 : Math.min(1, 0.18 + (Math.abs(weight) / peak) * 0.72);

interface FieldMapCardProps {
  payload: unknown;
  scenario?: string | null;
}

export const FieldMapCard = ({ payload, scenario = null }: FieldMapCardProps) => {
  const t = useT();
  const { activeId } = useOptionalScenario();
  const source = scenario ?? activeId;
  const wells = useScenarioDataset('wells', source);
  const graph = useScenarioDataset('graph', source);
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
    <div className="jarvis-field-map">
      <svg
        className="jarvis-field-map-plot"
        viewBox={`0 0 ${VIEW} ${VIEW}`}
        role="img"
        aria-label={`${t('jarvis-cards.mapFocus')} ${map.focus.join(', ')}`}
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
              className="jarvis-field-map-edge"
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
            className="jarvis-field-map-node"
            cx={point.x}
            cy={point.y}
            r={focus.has(id) ? 2.6 : 1.4}
            data-role={focus.has(id) ? 'focus' : highlight.has(id) ? 'highlight' : 'dim'}
          />
        ))}
      </svg>
      <p className="jarvis-field-map-meta">
        <span>
          {t('jarvis-cards.mapFocus')}: {map.focus.join(', ')}
        </span>
        <span>
          {t('jarvis-cards.mapEdges')}: {map.edges.length}
        </span>
      </p>
    </div>
  );
};
