export const TILE_WIDTH = 120;
export const TILE_HEIGHT = 36;
export const TILE_GAP = 6;
export const LABEL_HEIGHT = 12;
export const MIN_COLUMNS = 1;

export interface WallLayout {
  count: number;
  columns: number;
  rows: number;
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

export const layoutOf = (count: number, containerWidth: number): WallLayout => {
  const columns = Math.min(Math.max(count, MIN_COLUMNS), columnsFor(containerWidth));
  const rows = count === 0 ? 0 : Math.ceil(count / columns);
  const cellWidth = TILE_WIDTH + TILE_GAP;
  const cellHeight = TILE_HEIGHT + LABEL_HEIGHT + TILE_GAP;
  return {
    count,
    columns,
    rows,
    cellWidth,
    cellHeight,
    width: columns === 0 ? 0 : columns * cellWidth - TILE_GAP,
    height: rows === 0 ? 0 : rows * cellHeight - TILE_GAP
  };
};

export const tileX = (index: number, layout: WallLayout): number =>
  (index % layout.columns) * layout.cellWidth;

export const tileY = (index: number, layout: WallLayout): number =>
  Math.floor(index / layout.columns) * layout.cellHeight + LABEL_HEIGHT;

export const stepX = (step: number, steps: number): number =>
  steps <= 1 ? 0 : (step / (steps - 1)) * TILE_WIDTH;

export const stepAt = (offsetXWithinTile: number, steps: number): number => {
  if (steps <= 1) {
    return 0;
  }
  const ratio = offsetXWithinTile / TILE_WIDTH;
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
