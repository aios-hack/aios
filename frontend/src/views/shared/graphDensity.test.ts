import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import type { GraphFile } from '../../api/types';
import {
  EDGE_OPACITY_FLOOR,
  EDGE_OPACITY_SPAN,
  EDGE_WIDTH_FLOOR,
  EDGE_WIDTH_SPAN
} from '../../theme/tokens';
import { weightBounds } from '../FieldProjection/model';
import {
  DEFAULT_EDGE_BUDGET,
  defaultThreshold,
  edgeOpacity,
  edgeStrength,
  edgeWidth,
  visibleEdges
} from './graphModel';

const SHIPPED = [
  'graph.json',
  'base/graph.json',
  'policy-plan/graph.json',
  'whatif-injection-cut/graph.json'
];

const read = (name: string): GraphFile =>
  JSON.parse(
    readFileSync(join(process.cwd(), 'public', 'data', name), 'utf-8')
  ) as GraphFile;

describe('shipped connectivity graphs at the default threshold', () => {
  it('ships the dense graph the console actually opens on', () => {
    const graph = read('graph.json');
    expect(graph.nodes.length).toBe(103);
    expect(graph.edges.length).toBeGreaterThan(2000);
  });

  it.each(SHIPPED)('draws no more than the edge budget for %s', (name) => {
    const graph = read(name);
    const threshold = defaultThreshold(graph.edges, weightBounds(graph.edges));
    const shown = visibleEdges(graph.edges, threshold);
    expect(shown.length).toBeLessThanOrEqual(DEFAULT_EDGE_BUDGET);
    expect(DEFAULT_EDGE_BUDGET).toBeLessThanOrEqual(400);
  });

  it('still draws something, so the default is a filter and not a blackout', () => {
    for (const name of SHIPPED) {
      const graph = read(name);
      const threshold = defaultThreshold(graph.edges, weightBounds(graph.edges));
      expect(visibleEdges(graph.edges, threshold).length, name).toBeGreaterThan(0);
    }
  });

  it('keeps the strongest edges and drops the weakest ones', () => {
    const graph = read('graph.json');
    const threshold = defaultThreshold(graph.edges, weightBounds(graph.edges));
    const shown = visibleEdges(graph.edges, threshold);
    const strongest = Math.max(...graph.edges.map((edge) => Math.abs(edge.weight)));
    const weakest = Math.min(...graph.edges.map((edge) => Math.abs(edge.weight)));
    expect(shown.some((edge) => Math.abs(edge.weight) === strongest)).toBe(true);
    expect(shown.every((edge) => Math.abs(edge.weight) > weakest)).toBe(true);
  });

  it('encodes the surviving edges by magnitude, not by sign', () => {
    const graph = read('graph.json');
    const bounds = weightBounds(graph.edges);
    const shown = visibleEdges(graph.edges, defaultThreshold(graph.edges, bounds));
    const ranked = [...shown].sort((a, b) => Math.abs(b.weight) - Math.abs(a.weight));
    const strong = ranked[0];
    const faint = ranked[ranked.length - 1];
    expect(Math.abs(strong.weight)).toBeGreaterThan(Math.abs(faint.weight));
    expect(edgeWidth(strong.weight, bounds.max)).toBeGreaterThan(
      edgeWidth(faint.weight, bounds.max)
    );
    expect(edgeOpacity(strong.weight, bounds.max)).toBeGreaterThan(
      edgeOpacity(faint.weight, bounds.max)
    );
    expect(edgeWidth(-strong.weight, bounds.max)).toBe(
      edgeWidth(strong.weight, bounds.max)
    );
  });

  it('cuts a synthetic graph down to whatever budget it is handed', () => {
    const edges = Array.from({ length: 50 }, (_, index) => ({
      injector: `I${index}`,
      producer: `P${index}`,
      weight: (index + 1) / 50
    }));
    const bounds = weightBounds(edges);
    expect(visibleEdges(edges, defaultThreshold(edges, bounds, 5))).toHaveLength(5);
    expect(visibleEdges(edges, defaultThreshold(edges, bounds, 1))).toHaveLength(1);
    expect(visibleEdges(edges, defaultThreshold(edges, bounds, 500))).toHaveLength(50);
  });

  it('keeps the faintest surviving edge visible and the strongest at full weight', () => {
    expect(edgeOpacity(0, 0.9)).toBeCloseTo(EDGE_OPACITY_FLOOR);
    expect(edgeOpacity(0, 0.9)).toBeGreaterThan(0);
    expect(edgeWidth(0, 0.9)).toBeCloseTo(EDGE_WIDTH_FLOOR);
    expect(edgeOpacity(0.9, 0.9)).toBeCloseTo(EDGE_OPACITY_FLOOR + EDGE_OPACITY_SPAN);
    expect(edgeOpacity(0.9, 0.9)).toBeLessThanOrEqual(1);
    expect(edgeWidth(0.9, 0.9)).toBeCloseTo(EDGE_WIDTH_FLOOR + EDGE_WIDTH_SPAN);
  });

  it('reads strength off the magnitude and spreads the middle of the range', () => {
    expect(edgeStrength(0, 0.9)).toBe(0);
    expect(edgeStrength(-0.9, 0.9)).toBe(1);
    expect(edgeStrength(2, 0.9)).toBe(1);
    expect(edgeStrength(0.5, 0)).toBe(1);
    expect(edgeStrength(0.25, 1)).toBeGreaterThan(0.25);
    expect(edgeStrength(0.6, 1)).toBeGreaterThan(edgeStrength(0.25, 1));
  });

  it('leaves a user-chosen threshold in charge of what is drawn', () => {
    const graph = read('graph.json');
    const bounds = weightBounds(graph.edges);
    const openedUp = visibleEdges(graph.edges, bounds.min);
    const tightened = visibleEdges(graph.edges, bounds.max);
    expect(openedUp.length).toBe(graph.edges.length);
    expect(tightened.length).toBe(0);
    expect(openedUp.length).toBeGreaterThan(DEFAULT_EDGE_BUDGET);
  });
});
