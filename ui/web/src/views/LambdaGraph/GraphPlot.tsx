import { useEffect, useRef } from 'react';
import type { GraphFile, GraphNode } from '../../api/types';
import { useT } from '../../i18n/I18nContext';
import { graphColors, groupColor } from '../../theme/tokens';
import {
  edgeHighlighted,
  edgeOpacity,
  edgeWidth,
  groupIndex,
  nodeState,
  roundWeight,
  visibleEdges,
  type Selection,
  type WellFluidState
} from './model';
import { createViewBox, useViewBox } from './useViewBox';
import { WellGauge } from './WellGauge';

const PAD = 12;
const NODE_R = 2.6;
const LABEL_DY = -3.6;

// Порог, ниже которого подписи не рисуются. При обзорном масштабе 103 подписи
// занимают больше площади, чем сами узлы, и граф читается как каша: связность
// видна, а номера всё равно нечитаемы. Появляются они при увеличении, когда
// места под них действительно хватает.
const LABEL_MIN_SCALE = 1.8;

// Ниже этого масштаба подпись есть только у выбранного узла и его соседей.
const LABEL_SELECTION_SCALE = 1.0;

// Группа переехала с заливки на кольцо вокруг узла: заливка теперь занята
// уровнем обводнённости (задача 67), а участок остаётся различимым.
const groupRing = (node: GraphNode, index: Map<string, number>): string | null => {
  if (node.group === null) {
    return null;
  }
  return groupColor(index.get(node.group) ?? 0);
};

interface GraphPlotProps {
  data: GraphFile;
  threshold: number;
  selection: Selection | null;
  wellStates: Map<string, WellFluidState>;
  onSelect: (well: string) => void;
}

export const GraphPlot = ({
  data,
  threshold,
  selection,
  wellStates,
  onSelect
}: GraphPlotProps) => {
  const t = useT();
  const svgRef = useRef<SVGSVGElement | null>(null);
  const initial = createViewBox(data.layout?.size ?? 100, PAD);
  const { viewBox, zoomAtRatio, startPan, panBy, endPan, isPanning, hasDragged } =
    useViewBox(initial);

  // Колесо слушается нативно, а не через onWheel, ради одной строки —
  // preventDefault. Без неё браузер обрабатывает то же событие сам: обычным
  // колесом прокручивает страницу, а с Ctrl зумит её целиком, и граф
  // приближается вместе со всем интерфейсом.
  //
  // React вешает wheel на корневой контейнер пассивно, а в пассивном
  // слушателе preventDefault игнорируется молча — отсюда явный
  // addEventListener с { passive: false } на самом svg.
  useEffect(() => {
    const svg = svgRef.current;
    if (svg === null) {
      return;
    }
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      const factor = event.deltaY > 0 ? 1.12 : 1 / 1.12;
      const rect = svg.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) {
        zoomAtRatio(factor, 0.5, 0.5);
        return;
      }
      zoomAtRatio(
        factor,
        (event.clientX - rect.left) / rect.width,
        (event.clientY - rect.top) / rect.height
      );
    };
    svg.addEventListener('wheel', onWheel, { passive: false });
    return () => svg.removeEventListener('wheel', onWheel);
  }, [zoomAtRatio]);
  const index = groupIndex(data);
  const positions = new Map(data.nodes.map((node) => [node.id, node]));
  const shown = visibleEdges(data.edges, threshold);
  const maxWeight = data.weight_range?.max ?? 0;

  // Во сколько раз приблизили относительно обзорного вида.
  //
  // Размеры узлов, подписей и рёбер делятся на этот масштаб, то есть остаются
  // постоянными в экранных пикселях. Без этого зум бесполезен: и узлы, и
  // расстояния между ними заданы в единицах viewBox, растут одинаково, и
  // приближение даёт ту же кашу, только крупнее.
  const scale = initial.width / viewBox.width;
  const nodeR = NODE_R / scale;
  const labelSize = 3.1 / scale;
  const labelDy = LABEL_DY / scale;
  const strokeAt = (selected: boolean) => (selected ? 1.1 : 0.5) / scale;

  return (
    <svg
      ref={svgRef}
      className="lambda-graph-plot"
      viewBox={`${viewBox.x} ${viewBox.y} ${viewBox.width} ${viewBox.height}`}
      role="img"
      aria-label={t('graph.ariaLabel')}
      data-testid="lambda-graph-plot"
      onPointerDown={(event) => {
        startPan(event.clientX, event.clientY);
      }}
      onPointerMove={(event) => {
        if (!isPanning()) {
          return;
        }
        const rect = svgRef.current?.getBoundingClientRect();
        panBy(event.clientX, event.clientY, rect?.width ?? 0, rect?.height ?? 0);
      }}
      onPointerUp={endPan}
      onPointerLeave={endPan}
    >
      <g className="lambda-graph-edges">
        {shown.map((edge) => {
          const from = positions.get(edge.injector);
          const to = positions.get(edge.producer);
          if (!from || !to) {
            return null;
          }
          const strong = edgeHighlighted(edge, selection);
          return (
            <line
              key={`${edge.injector}-${edge.producer}`}
              x1={from.x}
              y1={from.y}
              x2={to.x}
              y2={to.y}
              stroke={strong ? graphColors.injector : graphColors.edge}
              strokeWidth={(edgeWidth(edge.weight, maxWeight) * (strong ? 2 : 1)) / scale}
              strokeOpacity={
                selection === null || strong ? edgeOpacity(edge.weight, maxWeight) : 0.12
              }
              strokeLinecap="round"
              data-edge-id={`${edge.injector}-${edge.producer}`}
              data-strong={strong}
            >
              <title>
                {t('graph.edge.title', {
                  injector: edge.injector,
                  producer: edge.producer,
                  weight: roundWeight(edge.weight)
                })}
              </title>
            </line>
          );
        })}
      </g>
      <g className="lambda-graph-nodes">
        {data.nodes.map((node) => {
          const state = nodeState(node, selection);
          // Подпись видна, когда под неё есть место: при обзорном масштабе —
          // только у выбранного узла и его соседей, при увеличении — у всех.
          const labelled =
            scale >= LABEL_MIN_SCALE ||
            (scale >= LABEL_SELECTION_SCALE && selection !== null && state !== 'faded');
          return (
            <g
              key={node.id}
              className="lambda-graph-node"
              data-well-id={node.id}
              data-role={node.role}
              data-state={state}
              data-group={node.group ?? ''}
              tabIndex={0}
              role="button"
              aria-label={`${node.id} — ${t(
                node.role === 'INJ' ? 'graph.node.injector' : 'graph.node.producer'
              )}`}
              onClick={() => {
                if (hasDragged()) {
                  return;
                }
                onSelect(node.id);
              }}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault();
                  onSelect(node.id);
                }
              }}
            >
              {groupRing(node, index) !== null && state !== 'faded' && (
                <circle
                  cx={node.x}
                  cy={node.y}
                  r={nodeR * 1.55}
                  fill="none"
                  stroke={groupRing(node, index) ?? ''}
                  strokeWidth={0.4 / scale}
                  opacity={0.55}
                />
              )}
              <WellGauge
                id={node.id}
                x={node.x}
                y={node.y}
                r={nodeR}
                role={node.role}
                watercut={wellStates.get(node.id)?.watercut ?? null}
                commissioned={wellStates.get(node.id)?.commissioned ?? true}
                state={state}
                strokeWidth={strokeAt(state === 'selected')}
              />
              <circle
                className="lambda-graph-focus"
                cx={node.x}
                cy={node.y}
                r={nodeR * 1.9}
                strokeWidth={1.4 / scale}
              />
              {labelled ? (
                <text
                  className="lambda-graph-label"
                  x={node.x}
                  y={node.y + labelDy}
                  fontSize={labelSize}
                  textAnchor="middle"
                  fill={state === 'faded' ? graphColors.muted : graphColors.text}
                >
                  {node.id}
                </text>
              ) : null}
              <title>{node.id}</title>
            </g>
          );
        })}
      </g>
    </svg>
  );
};
