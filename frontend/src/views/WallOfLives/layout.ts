export const TILE_WIDTH = 120;
export const TILE_HEIGHT = 36;
export const TILE_GAP = 6;
export const LABEL_HEIGHT = 12;
export const MIN_COLUMNS = 1;

export const TILE_WIDTH_MAX = 220;
export const TILE_HEIGHT_MAX = 96;

export interface WallLayout {
  count: number;
  columns: number;
  rows: number;
  tileWidth: number;
  tileHeight: number;
  cellWidth: number;
  cellHeight: number;
  width: number;
  height: number;
}

export const columnsFor = (containerWidth: number): number => {
  const usable = containerWidth + TILE_GAP;
  const perTile = TILE_WIDTH + TILE_GAP;
  return Math.max(MIN_COLUMNS, Math.floor(usable / perTile));
};

export const tileWidthFor = (columns: number, containerWidth: number): number => {
  if (columns <= 0 || !Number.isFinite(containerWidth) || containerWidth <= 0) {
    return TILE_WIDTH;
  }
  const room = containerWidth - (columns - 1) * TILE_GAP;
  const fitted = room / columns;
  if (fitted <= TILE_WIDTH) {
    return TILE_WIDTH;
  }
  return Math.min(fitted, TILE_WIDTH_MAX);
};

export const tileHeightFor = (rows: number, containerHeight: number): number => {
  if (rows <= 0 || !Number.isFinite(containerHeight) || containerHeight <= 0) {
    return TILE_HEIGHT;
  }
  const room = containerHeight - rows * (LABEL_HEIGHT + TILE_GAP) + TILE_GAP;
  const fitted = room / rows;
  if (fitted <= TILE_HEIGHT) {
    return TILE_HEIGHT;
  }
  return Math.min(Math.floor(fitted), TILE_HEIGHT_MAX);
};

export const layoutOf = (
  count: number,
  containerWidth: number,
  containerHeight = 0
): WallLayout => {
  const columns = Math.min(Math.max(count, MIN_COLUMNS), columnsFor(containerWidth));
  const rows = count === 0 ? 0 : Math.ceil(count / columns);
  const tileWidth = tileWidthFor(columns, containerWidth);
  const tileHeight = tileHeightFor(rows, containerHeight);
  const cellWidth = tileWidth + TILE_GAP;
  const cellHeight = tileHeight + LABEL_HEIGHT + TILE_GAP;
  return {
    count,
    columns,
    rows,
    tileWidth,
    tileHeight,
    cellWidth,
    cellHeight,
    width: columns === 0 ? 0 : Math.round(columns * cellWidth - TILE_GAP),
    height: rows === 0 ? 0 : rows * cellHeight - TILE_GAP
  };
};

export const tileX = (index: number, layout: WallLayout): number =>
  (index % layout.columns) * layout.cellWidth;

export const tileY = (index: number, layout: WallLayout): number =>
  Math.floor(index / layout.columns) * layout.cellHeight + LABEL_HEIGHT;

export const stepX = (
  step: number,
  steps: number,
  tileWidth: number = TILE_WIDTH
): number => (steps <= 1 ? 0 : (step / (steps - 1)) * tileWidth);

export const stepAt = (
  offsetXWithinTile: number,
  steps: number,
  tileWidth: number = TILE_WIDTH
): number => {
  if (steps <= 1) {
    return 0;
  }
  const ratio = offsetXWithinTile / tileWidth;
  const step = Math.round(ratio * (steps - 1));
  return Math.min(Math.max(step, 0), steps - 1);
};

export const tileIndexAt = (
  offsetX: number,
  offsetY: number,
  layout: WallLayout
): number | null => {
  if (offsetX < 0 || offsetY < 0 || layout.columns === 0) {
    return null;
  }
  const column = Math.floor(offsetX / layout.cellWidth);
  const row = Math.floor(offsetY / layout.cellHeight);
  if (column >= layout.columns || row >= layout.rows) {
    return null;
  }
  const index = row * layout.columns + column;
  return index < layout.count ? index : null;
};
