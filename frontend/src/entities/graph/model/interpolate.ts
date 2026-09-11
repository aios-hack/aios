export interface Point {
  x: number;
  y: number;
}

export interface LabelledPoint extends Point {
  id: string;
}

export interface Box {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface ProjectedNode {
  id: string;
  map: Point | null;
  graph: Point | null;
}

export interface PlacedNode {
  id: string;
  x: number;
  y: number;
  presence: number;
  onlyMap: boolean;
  onlyGraph: boolean;
}

export const lerp = (from: number, to: number, t: number): number =>
  from + (to - from) * t;

export const easeInOut = (t: number): number => {
  if (t <= 0) {
    return 0;
  }
  if (t >= 1) {
    return 1;
  }
  return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
};

export const fitLayout = (points: LabelledPoint[], box: Box): Map<string, Point> => {
  const fitted = new Map<string, Point>();
  if (points.length === 0) {
    return fitted;
  }
  let minX = points[0].x;
  let maxX = points[0].x;
  let minY = points[0].y;
  let maxY = points[0].y;
  for (const point of points) {
    minX = Math.min(minX, point.x);
    maxX = Math.max(maxX, point.x);
    minY = Math.min(minY, point.y);
    maxY = Math.max(maxY, point.y);
  }
  const spanX = maxX - minX;
  const spanY = maxY - minY;
  const scale =
    spanX <= 0 && spanY <= 0
      ? 1
      : Math.min(
          spanX > 0 ? box.width / spanX : Number.POSITIVE_INFINITY,
          spanY > 0 ? box.height / spanY : Number.POSITIVE_INFINITY
        );
  const offsetX = box.x + (box.width - spanX * scale) / 2;
  const offsetY = box.y + (box.height - spanY * scale) / 2;
  for (const point of points) {
    fitted.set(point.id, {
      x: offsetX + (point.x - minX) * scale,
      y: offsetY + (point.y - minY) * scale
    });
  }
  return fitted;
};

export const placeNodes = (nodes: ProjectedNode[], t: number): PlacedNode[] => {
  const placed: PlacedNode[] = [];
  for (const node of nodes) {
    const onlyMap = node.graph === null;
    const onlyGraph = node.map === null;
    const anchor = node.map ?? node.graph;
    if (anchor === null) {
      continue;
    }
    const target = node.graph ?? anchor;
    const source = node.map ?? anchor;
    placed.push({
      id: node.id,
      x: lerp(source.x, target.x, t),
      y: lerp(source.y, target.y, t),
      presence: onlyMap ? 1 - t : onlyGraph ? t : 1,
      onlyMap,
      onlyGraph
    });
  }
  return placed;
};

export const edgeOpacityAt = (t: number, base: number): number =>
  t <= 0 ? 0 : base * t;
