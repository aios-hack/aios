import { describe, expect, it } from 'vitest';
import type { LayerRange, WellPoint, WellsFile } from '../../api/types';
import {
  dimmedWellIds,
  isWellDimmed,
  layerOptions,
  shownCount,
  type LayerFilter
} from './layerFilter';
import {
  easeInOut,
  edgeOpacityAt,
  fitLayout,
  lerp,
  placeNodes,
  type LabelledPoint,
  type ProjectedNode
} from './interpolate';
import { coalescedZoom, FRAME_BUDGET_MS, shouldCommitFrame, ZOOM_STEP } from './useProjection';

const layer = (id: number): LayerRange => ({ id, k_min: id, k_max: id + 1 });

const well = (id: string, layers: number[]): WellPoint => ({
  id,
  i: 0,
  j: 0,
  completions: [],
  layers
});

const file = (wells: WellPoint[], layers: LayerRange[] = []): WellsFile =>
  ({ grid: { ni: 10, nj: 10, nk: 3 }, layers, wells }) as unknown as WellsFile;

const WELLS = file([well('A', [1, 2]), well('B', [2]), well('C', [])], [layer(1), layer(2)]);

describe('layerOptions', () => {
  it('offers an all-layers option ahead of every layer', () => {
    expect(layerOptions([layer(1), layer(2)])).toEqual([
      { value: 'all', id: null },
      { value: 1, id: 1 },
      { value: 2, id: 2 }
    ]);
  });

  it('still offers the all-layers option when the grid has no layers', () => {
    expect(layerOptions([])).toEqual([{ value: 'all', id: null }]);
  });
});

describe('isWellDimmed', () => {
  it('dims nothing while every layer is shown', () => {
    expect(isWellDimmed(well('A', [1]), 'all')).toBe(false);
    expect(isWellDimmed(well('C', []), 'all')).toBe(false);
  });

  it('dims the wells that miss the chosen layer', () => {
    expect(isWellDimmed(well('A', [1, 2]), 1)).toBe(false);
    expect(isWellDimmed(well('B', [2]), 1)).toBe(true);
    expect(isWellDimmed(well('C', []), 1)).toBe(true);
  });
});

describe('shownCount', () => {
  it('counts every well while the filter is off', () => {
    expect(shownCount(WELLS, 'all')).toBe(3);
  });

  it('counts only the wells perforating the chosen layer', () => {
    expect(shownCount(WELLS, 1)).toBe(1);
    expect(shownCount(WELLS, 2)).toBe(2);
  });

  it('counts nobody for a layer no well reaches', () => {
    expect(shownCount(WELLS, 9)).toBe(0);
  });

  it('counts nothing in an empty field', () => {
    expect(shownCount(file([]), 'all')).toBe(0);
    expect(shownCount(file([]), 1)).toBe(0);
  });
});

describe('dimmedWellIds', () => {
  it('dims nobody while every layer is shown', () => {
    expect(dimmedWellIds(WELLS, 'all').size).toBe(0);
  });

  it('names exactly the wells that miss the chosen layer', () => {
    expect([...dimmedWellIds(WELLS, 1)]).toEqual(['B', 'C']);
  });

  it('agrees with the count of what is left visible', () => {
    for (const filter of ['all', 1, 2, 9] as LayerFilter[]) {
      expect(WELLS.wells.length - dimmedWellIds(WELLS, filter).size).toBe(
        shownCount(WELLS, filter)
      );
    }
  });
});

describe('lerp', () => {
  it('pins the ends and halves the middle', () => {
    expect(lerp(10, 20, 0)).toBe(10);
    expect(lerp(10, 20, 1)).toBe(20);
    expect(lerp(10, 20, 0.5)).toBe(15);
  });

  it('extrapolates past the ends rather than clamping', () => {
    expect(lerp(0, 10, 2)).toBe(20);
    expect(lerp(0, 10, -1)).toBe(-10);
  });
});

describe('easeInOut', () => {
  it('pins both ends of the transition', () => {
    expect(easeInOut(0)).toBe(0);
    expect(easeInOut(1)).toBe(1);
    expect(easeInOut(0.5)).toBeCloseTo(0.5);
  });

  it('clamps positions outside the transition', () => {
    expect(easeInOut(-3)).toBe(0);
    expect(easeInOut(4)).toBe(1);
  });

  it('never runs backwards', () => {
    const steps = Array.from({ length: 21 }, (_, index) => easeInOut(index / 20));
    for (let index = 1; index < steps.length; index += 1) {
      expect(steps[index]).toBeGreaterThanOrEqual(steps[index - 1]);
    }
  });

  it('starts slow and ends slow', () => {
    expect(easeInOut(0.25)).toBeLessThan(0.25);
    expect(easeInOut(0.75)).toBeGreaterThan(0.75);
  });
});

describe('fitLayout', () => {
  const box = { x: 0, y: 0, width: 100, height: 100 };

  it('fits nothing from no points', () => {
    expect(fitLayout([], box).size).toBe(0);
  });

  it('stretches the cloud to the box without distorting it', () => {
    const points: LabelledPoint[] = [
      { id: 'a', x: 0, y: 0 },
      { id: 'b', x: 10, y: 5 }
    ];
    const fitted = fitLayout(points, box);
    expect(fitted.get('a')).toEqual({ x: 0, y: 25 });
    expect(fitted.get('b')).toEqual({ x: 100, y: 75 });
  });

  it('centres a single point instead of dividing by a zero span', () => {
    const fitted = fitLayout([{ id: 'a', x: 7, y: 7 }], box);
    expect(fitted.get('a')).toEqual({ x: 50, y: 50 });
  });

  it('honours the box offset', () => {
    const fitted = fitLayout(
      [
        { id: 'a', x: 0, y: 0 },
        { id: 'b', x: 1, y: 1 }
      ],
      { x: 20, y: 30, width: 100, height: 100 }
    );
    expect(fitted.get('a')).toEqual({ x: 20, y: 30 });
    expect(fitted.get('b')).toEqual({ x: 120, y: 130 });
  });
});

describe('placeNodes', () => {
  const nodes: ProjectedNode[] = [
    { id: 'both', map: { x: 0, y: 0 }, graph: { x: 100, y: 50 } },
    { id: 'onlyMap', map: { x: 10, y: 10 }, graph: null },
    { id: 'onlyGraph', map: null, graph: { x: 20, y: 20 } },
    { id: 'nowhere', map: null, graph: null }
  ];

  it('leaves every node at its map position at the start', () => {
    const placed = placeNodes(nodes, 0);
    expect(placed.map((node) => node.id)).toEqual(['both', 'onlyMap', 'onlyGraph']);
    expect(placed[0]).toMatchObject({ x: 0, y: 0, presence: 1 });
  });

  it('carries every node to its graph position at the end', () => {
    const placed = placeNodes(nodes, 1);
    expect(placed[0]).toMatchObject({ x: 100, y: 50 });
  });

  it('interpolates halfway through the transition', () => {
    expect(placeNodes(nodes, 0.5)[0]).toMatchObject({ x: 50, y: 25 });
  });

  it('fades a map-only node out and a graph-only node in', () => {
    const start = placeNodes(nodes, 0);
    const end = placeNodes(nodes, 1);
    expect(start[1].presence).toBe(1);
    expect(end[1].presence).toBe(0);
    expect(start[2].presence).toBe(0);
    expect(end[2].presence).toBe(1);
  });

  it('anchors a one-sided node so it never jumps', () => {
    for (const t of [0, 0.5, 1]) {
      const placed = placeNodes(nodes, t);
      expect(placed[1]).toMatchObject({ x: 10, y: 10, onlyMap: true });
      expect(placed[2]).toMatchObject({ x: 20, y: 20, onlyGraph: true });
    }
  });

  it('drops a node that has no position at all', () => {
    expect(placeNodes(nodes, 0.5).some((node) => node.id === 'nowhere')).toBe(false);
    expect(placeNodes([], 0.5)).toEqual([]);
  });
});

describe('edgeOpacityAt', () => {
  it('hides the graph edges while the map is still shown', () => {
    expect(edgeOpacityAt(0, 0.6)).toBe(0);
    expect(edgeOpacityAt(-1, 0.6)).toBe(0);
  });

  it('reaches full strength at the end of the transition', () => {
    expect(edgeOpacityAt(1, 0.6)).toBeCloseTo(0.6);
    expect(edgeOpacityAt(0.5, 0.6)).toBeCloseTo(0.3);
  });
});

describe('shouldCommitFrame', () => {
  it('holds the commit until the frame budget has passed', () => {
    expect(shouldCommitFrame(100, 100, 0)).toBe(false);
    expect(shouldCommitFrame(100 + FRAME_BUDGET_MS - 1, 100, 0)).toBe(false);
    expect(shouldCommitFrame(100 + FRAME_BUDGET_MS, 100, 0)).toBe(true);
  });

  it('stretches the interval when the previous commit was slow', () => {
    expect(shouldCommitFrame(140, 100, 60)).toBe(false);
    expect(shouldCommitFrame(160, 100, 60)).toBe(true);
  });

  it('never shrinks below the frame budget for a cheap commit', () => {
    expect(shouldCommitFrame(100 + FRAME_BUDGET_MS, 100, 2)).toBe(true);
  });
});

describe('coalescedZoom', () => {
  it('leaves the view untouched when nothing was scrolled', () => {
    expect(coalescedZoom([])).toBe(1);
  });

  it('matches a single wheel notch', () => {
    expect(coalescedZoom([1])).toBeCloseTo(ZOOM_STEP);
    expect(coalescedZoom([-1])).toBeCloseTo(1 / ZOOM_STEP);
  });

  it('multiplies the notches gathered inside one frame', () => {
    expect(coalescedZoom([1, 1, 1])).toBeCloseTo(ZOOM_STEP ** 3);
  });

  it('cancels opposite notches', () => {
    expect(coalescedZoom([1, -1])).toBeCloseTo(1);
  });
});
