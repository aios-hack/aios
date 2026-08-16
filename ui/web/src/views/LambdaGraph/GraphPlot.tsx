import { useRef } from 'react';
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
  type Selection
} from './model';
import { createViewBox, useViewBox } from './useViewBox';

const PAD = 12;
const NODE_R = 2.6;
const LABEL_DY = -3.6;

const nodeFill = (node: GraphNode, index: Map<string, number>): string => {
  if (node.group === null) {
    return graphColors.dim;
  }
  return groupColor(index.get(node.group) ?? 0);
};

const trianglePath = (x: number, y: number, r: number): string =>
  `M ${x} ${y - r * 1.15} L ${x + r} ${y + r * 0.8} L ${x - r} ${y + r * 0.8} Z`;

interface GraphPlotProps {
  data: GraphFile;
  threshold: number;
  selection: Selection | null;
  onSelect: (well: string) => void;
}

export const GraphPlot = ({ data, threshold, selection, onSelect }: GraphPlotProps) => {
  const t = useT();
  const svgRef = useRef<SVGSVGElement | null>(null);
  const initial = createViewBox(data.layout?.size ?? 100, PAD);
  const { viewBox, zoomBy, startPan, panBy, endPan, isPanning, hasDragged } =
    useViewBox(initial);
  const index = groupIndex(data);
  const positions = new Map(data.nodes.map((node) => [node.id, node]));
  const shown = visibleEdges(data.edges, threshold);
  const maxWeight = data.weight_range?.max ?? 0;

  return (
    <svg
      ref={svgRef}
      className="lambda-graph-plot"
      viewBox={`${viewBox.x} ${viewBox.y} ${viewBox.width} ${viewBox.height}`}
      role="img"
      aria-label={t('graph.ariaLabel')}
      data-testid="lambda-graph-plot"
      onWheel={(event) => {
        const rect = svgRef.current?.getBoundingClientRect();
        const factor = event.deltaY > 0 ? 1.12 : 1 / 1.12;
        if (!rect || rect.width === 0 || rect.height === 0) {
          zoomBy(factor, viewBox.x + viewBox.width / 2, viewBox.y + viewBox.height / 2);
          return;
        }
        const ratioX = (event.clientX - rect.left) / rect.width;
        const ratioY = (event.clientY - rect.top) / rect.height;
        zoomBy(factor, viewBox.x + ratioX * viewBox.width, viewBox.y + ratioY * viewBox.height);
      }}
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
              strokeWidth={edgeWidth(edge.weight, maxWeight) * (strong ? 2 : 1)}
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
          const fill = state === 'faded' ? graphColors.dim : nodeFill(node, index);
          const stroke =
            node.role === 'INJ' ? graphColors.injector : graphColors.producer;
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
              {node.role === 'INJ' ? (
                <path
                  d={trianglePath(node.x, node.y, NODE_R)}
                  fill={fill}
                  stroke={stroke}
                  strokeWidth={state === 'selected' ? 1.1 : 0.5}
                />
              ) : (
                <circle
                  cx={node.x}
                  cy={node.y}
                  r={NODE_R}
                  fill={fill}
                  stroke={stroke}
                  strokeWidth={state === 'selected' ? 1.1 : 0.5}
                />
              )}
              <text
                className="lambda-graph-label"
                x={node.x}
                y={node.y + LABEL_DY}
                fontSize={3.1}
                textAnchor="middle"
                fill={state === 'faded' ? graphColors.muted : graphColors.text}
              >
                {node.id}
              </text>
            </g>
          );
        })}
      </g>
    </svg>
  );
};
