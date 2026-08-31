import { describe, expect, it } from 'vitest';
import type { GraphEdge, GraphFile, GraphNode } from '../../api/types';
import {
  DEFAULT_EDGE_QUANTILE,
  EDGES_PER_PRODUCER,
  buildSelection,
  defaultThreshold,
  edgeHighlighted,
  edgeOpacity,
  edgeWidth,
  formatWindowDate,
  groupIndex,
  nodeState,
  roundWeight,
  topEdgesPerProducer,
  visibleEdges
} from './graphModel';

const edge = (injector: string, producer: string, weight: number): GraphEdge => ({
  injector,
  producer,
  weight
});

const node = (id: string, group: string | null, role: 'INJ' | 'PROD'): GraphNode => ({
  id,
  role,
  group,
  x: 0,
  y: 0
});

const EDGES: GraphEdge[] = [
  edge('I1', 'P1', 0.9),
  edge('I2', 'P1', -0.5),
  edge('I1', 'P2', 0.2),
  edge('I3', 'P2', 0.05)
];

const BOUNDS = { min: 0.05, max: 0.9 };

const graph = (): GraphFile =>
  ({
    window: { start: '2007-01-01', end: '2007-06-30' },
    nodes: [
      node('I1', 'G1', 'INJ'),
      node('P1', 'G1', 'PROD'),
      node('P2', 'G2', 'PROD'),
      node('P3', null, 'PROD')
    ],
    edges: EDGES,
    groups: [
      { id: 'G1', wells: ['I1', 'P1'] },
      { id: 'G2', wells: ['P2'] }
    ],
    weight_range: BOUNDS,
    meta: {},
    layout: { size: 100, seed: 1 }
  }) as unknown as GraphFile;

describe('groupIndex', () => {
  it('numbers the groups in the order the graph lists them', () => {
    expect(groupIndex(graph())).toEqual(
      new Map([
        ['G1', 0],
        ['G2', 1]
      ])
    );
  });
});

describe('visibleEdges', () => {
  it('keeps the edges at or above the threshold, by magnitude', () => {
    expect(visibleEdges(EDGES, 0.5)).toHaveLength(2);
    expect(visibleEdges(EDGES, 0.5).map((item) => item.weight)).toEqual([0.9, -0.5]);
  });

  it('judges a negative edge by its strength, not its sign', () => {
    expect(visibleEdges([edge('I1', 'P1', -0.9)], 0.5)).toHaveLength(1);
  });

  it('shows everything at a threshold of zero and nothing above the strongest', () => {
    expect(visibleEdges(EDGES, 0)).toHaveLength(EDGES.length);
    expect(visibleEdges(EDGES, 1)).toHaveLength(0);
  });

  it('only ever loses edges as the threshold rises', () => {
    let previous = EDGES.length;
    for (const threshold of [0, 0.05, 0.2, 0.5, 0.9, 1]) {
      const count = visibleEdges(EDGES, threshold).length;
      expect(count).toBeLessThanOrEqual(previous);
      previous = count;
    }
  });

  it('never mutates the edges it was given', () => {
    const before = [...EDGES];
    visibleEdges(EDGES, 0.5);
    expect(EDGES).toEqual(before);
  });
});

describe('defaultThreshold', () => {
  it('starts with every edge visible', () => {
    expect(DEFAULT_EDGE_QUANTILE).toBe(0);
    const threshold = defaultThreshold(EDGES, BOUNDS);
    expect(visibleEdges(EDGES, threshold)).toHaveLength(EDGES.length);
  });

  it('lands on the weakest edge in the graph', () => {
    expect(defaultThreshold(EDGES, BOUNDS)).toBeCloseTo(0.05);
  });

  it('falls back to the lower bound when there are no edges at all', () => {
    expect(defaultThreshold([], BOUNDS)).toBe(BOUNDS.min);
    expect(visibleEdges([], defaultThreshold([], BOUNDS))).toEqual([]);
  });

  it('handles a single edge without reading past the end', () => {
    const single = [edge('I1', 'P1', 0.4)];
    expect(defaultThreshold(single, BOUNDS)).toBeCloseTo(0.4);
    expect(visibleEdges(single, defaultThreshold(single, BOUNDS))).toHaveLength(1);
  });

  it('never mutates the edges it was given', () => {
    const shuffled = [edge('I1', 'P1', 0.9), edge('I2', 'P2', 0.1)];
    const before = shuffled.map((item) => item.weight);
    defaultThreshold(shuffled, BOUNDS);
    expect(shuffled.map((item) => item.weight)).toEqual(before);
  });
});

describe('topEdgesPerProducer', () => {
  it('keeps only the strongest edges reaching each producer', () => {
    const kept = topEdgesPerProducer(EDGES, 1);
    expect(kept).toHaveLength(2);
    expect(kept.map((item) => item.weight).sort()).toEqual([0.2, 0.9]);
  });

  it('keeps everything when no limit is asked for', () => {
    expect(topEdgesPerProducer(EDGES, null)).toHaveLength(EDGES.length);
  });

  it('keeps nothing at a limit of zero', () => {
    expect(topEdgesPerProducer(EDGES, 0)).toEqual([]);
  });

  it('leaves a producer alone when it has fewer edges than the limit', () => {
    expect(topEdgesPerProducer(EDGES, EDGES_PER_PRODUCER)).toHaveLength(EDGES.length);
  });

  it('ranks by strength, not by sign', () => {
    const edges = [edge('I1', 'P1', 0.1), edge('I2', 'P1', -0.8)];
    expect(topEdgesPerProducer(edges, 1)[0].injector).toBe('I2');
  });

  it('keeps nothing from no edges', () => {
    expect(topEdgesPerProducer([], 2)).toEqual([]);
  });
});

describe('edgeOpacity and edgeWidth', () => {
  it('grows with the strength of the edge', () => {
    expect(edgeOpacity(0.9, 0.9)).toBeGreaterThan(edgeOpacity(0.2, 0.9));
    expect(edgeWidth(0.9, 0.9)).toBeGreaterThan(edgeWidth(0.2, 0.9));
  });

  it('reads a negative edge at its magnitude', () => {
    expect(edgeOpacity(-0.9, 0.9)).toBe(edgeOpacity(0.9, 0.9));
    expect(edgeWidth(-0.9, 0.9)).toBe(edgeWidth(0.9, 0.9));
  });

  it('falls back to a fixed look when the graph has no scale', () => {
    expect(edgeOpacity(0.5, 0)).toBe(1);
    expect(edgeWidth(0.5, 0)).toBe(0.4);
  });
});

describe('buildSelection', () => {
  it('collects the group members and the connected wells', () => {
    const selection = buildSelection('P1', graph(), 0.4);
    expect(selection.group).toBe('G1');
    expect([...selection.members]).toEqual(['I1', 'P1']);
    expect([...selection.neighbours]).toEqual(['I1', 'I2']);
  });

  it('drops the neighbours that the threshold hides', () => {
    expect([...buildSelection('P1', graph(), 0.8).neighbours]).toEqual(['I1']);
  });

  it('reports no group for a well the graph never placed', () => {
    const selection = buildSelection('P3', graph(), 0);
    expect(selection.group).toBeNull();
    expect(selection.members.size).toBe(0);
  });

  it('reports an empty selection for a well the graph does not know', () => {
    const selection = buildSelection('X9', graph(), 0);
    expect(selection.well).toBe('X9');
    expect(selection.group).toBeNull();
    expect(selection.neighbours.size).toBe(0);
  });
});

describe('nodeState', () => {
  const selection = buildSelection('P1', graph(), 0.4);

  it('leaves every node plain while nothing is selected', () => {
    expect(nodeState(node('P2', 'G2', 'PROD'), null)).toBe('plain');
  });

  it('ranks the selected well above its neighbours and its group', () => {
    expect(nodeState(node('P1', 'G1', 'PROD'), selection)).toBe('selected');
    expect(nodeState(node('I1', 'G1', 'INJ'), selection)).toBe('neighbour');
    expect(nodeState(node('I2', 'G3', 'INJ'), selection)).toBe('neighbour');
    expect(nodeState(node('P2', 'G2', 'PROD'), selection)).toBe('faded');
  });
});

describe('edgeHighlighted', () => {
  const selection = buildSelection('P1', graph(), 0.4);

  it('highlights only the edges touching the selected well', () => {
    expect(edgeHighlighted(edge('I1', 'P1', 0.9), selection)).toBe(true);
    expect(edgeHighlighted(edge('P1', 'P2', 0.9), selection)).toBe(true);
    expect(edgeHighlighted(edge('I1', 'P2', 0.9), selection)).toBe(false);
  });

  it('highlights nothing while nothing is selected', () => {
    expect(edgeHighlighted(edge('I1', 'P1', 0.9), null)).toBe(false);
  });
});

describe('formatWindowDate and roundWeight', () => {
  it('turns an ISO date into the day-first form the panel shows', () => {
    expect(formatWindowDate('2007-06-30')).toBe('30.06.2007');
  });

  it('passes anything that is not a date straight through', () => {
    expect(formatWindowDate('2007-06')).toBe('2007-06');
    expect(formatWindowDate('')).toBe('');
  });

  it('shows a weight at three decimals', () => {
    expect(roundWeight(0.12345)).toBe('0.123');
    expect(roundWeight(-1)).toBe('-1.000');
  });
});
