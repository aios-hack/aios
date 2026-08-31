import { useMemo } from 'react';
import type { GraphEdge, GraphFile, WellsFile } from '../../api/types';
import { dataOf, useDataset } from '../../data';
import { useTimeline } from '../../state/TimelineContext';
import {
  npvByWell,
  npvCeiling,
  rateCeiling,
  rowsAtStep,
  wellStateOf,
  type WellState
} from '../shared/wellState';
import { defaultThreshold, visibleEdges } from '../shared/graphModel';
import { fitLayout, placeNodes, type Box, type ProjectedNode } from './interpolate';

export const FIELD_SIZE = 100;
export const FIELD_PAD = 10;

const INNER: Box = { x: 0, y: 0, width: FIELD_SIZE, height: FIELD_SIZE };

export const projectNodes = (wells: WellsFile, graph: GraphFile): ProjectedNode[] => {
  const mapLayout = fitLayout(
    wells.wells.map((well) => ({ id: well.id, x: well.i, y: well.j })),
    INNER
  );
  const graphLayout = fitLayout(
    graph.nodes.map((node) => ({ id: node.id, x: node.x, y: node.y })),
    INNER
  );
  const ids = new Set<string>([...mapLayout.keys(), ...graphLayout.keys()]);
  return [...ids].map((id) => ({
    id,
    map: mapLayout.get(id) ?? null,
    graph: graphLayout.get(id) ?? null
  }));
};

export const weightBounds = (edges: GraphEdge[]): { min: number; max: number } => {
  const weights = edges.map((edge) => Math.abs(edge.weight));
  const top = weights.length > 0 ? Math.max(...weights) : 0;
  return {
    min: weights.length > 0 ? Math.min(...weights) : 0,
    max: top > 0 ? top * 1.02 : 0
  };
};

export const useProjectionGeometry = (
  wells: WellsFile,
  graph: GraphFile,
  blend: number,
  threshold: number | null
) => {
  const projected = useMemo(() => projectNodes(wells, graph), [wells, graph]);
  const placed = useMemo(() => placeNodes(projected, blend), [projected, blend]);
  const placedIndex = useMemo(
    () => new Map(placed.map((node) => [node.id, node])),
    [placed]
  );
  const withoutConnectivity = useMemo(
    () => projected.filter((node) => node.graph === null).length,
    [projected]
  );
  const bounds = useMemo(() => weightBounds(graph.edges), [graph]);
  const activeThreshold = threshold ?? defaultThreshold(graph.edges, bounds);
  const edges = useMemo(
    () => visibleEdges(graph.edges, activeThreshold),
    [graph, activeThreshold]
  );
  return { placed, placedIndex, withoutConnectivity, bounds, activeThreshold, edges };
};

export const useWellStates = (): Map<string, WellState> => {
  const { timeline, stepIndex } = useTimeline();
  const npvState = useDataset('npv');
  const timelineData = timeline.status === 'ready' ? timeline.data : null;
  const rateMax = useMemo(() => rateCeiling(timelineData), [timelineData]);
  const rows = useMemo(() => rowsAtStep(timelineData, stepIndex), [timelineData, stepIndex]);
  const npv = useMemo(() => npvByWell(dataOf(npvState)), [npvState]);
  const npvMax = useMemo(() => npvCeiling(npv), [npv]);
  return useMemo(() => {
    const map = new Map<string, WellState>();
    for (const [id, row] of rows) {
      map.set(id, wellStateOf(row, { metric: 'watercut', rateMax, npv, npvMax }));
    }
    return map;
  }, [rows, rateMax, npv, npvMax]);
};
