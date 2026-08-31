export const CELL_WIDTH = 5;
export const CELL_HEIGHT = 7;
export const ROW_GAP = 1;
export const COLUMN_GAP = 1;
export const CELL_HEIGHT_MAX = 14;
export const GUTTER_LEFT = 58;
export const GUTTER_TOP = 18;
export const GUTTER_RIGHT = 12;
export const LABEL_MIN_GAP = 11;
export const CELL_WIDTH_MAX = 16;

export interface ChronoGeometry {
  columns: number;
  rows: number;
  cellWidth: number;
  cellHeight: number;
  plotWidth: number;
  plotHeight: number;
  width: number;
  height: number;
}

export const cellHeightFor = (
  rows: number,
  available: number,
  ratio: number = 1
): number => {
  if (rows <= 0 || !Number.isFinite(available)) {
    return CELL_HEIGHT;
  }
  const room = available - GUTTER_TOP;
  if (room <= 0) {
    return CELL_HEIGHT;
  }
  const fitted = room / rows;
  if (fitted <= CELL_HEIGHT) {
    return CELL_HEIGHT;
  }
  const capped = Math.min(fitted, CELL_HEIGHT_MAX);
  const scale = Number.isFinite(ratio) && ratio > 0 ? ratio : 1;
  const quantised = Math.floor(capped * scale) / scale;
  return quantised >= CELL_HEIGHT ? quantised : CELL_HEIGHT;
};

export const cellWidthFor = (
  columns: number,
  available: number,
  ratio: number = 1
): number => {
  if (columns <= 0 || !Number.isFinite(available)) {
    return CELL_WIDTH;
  }
  const room = available - GUTTER_LEFT - GUTTER_RIGHT;
  if (room <= 0) {
    return CELL_WIDTH;
  }
  const fitted = room / columns;
  if (fitted <= CELL_WIDTH) {
    return CELL_WIDTH;
  }
  const capped = Math.min(fitted, CELL_WIDTH_MAX);
  const scale = Number.isFinite(ratio) && ratio > 0 ? ratio : 1;
  const quantised = Math.floor(capped * scale) / scale;
  return quantised >= CELL_WIDTH ? quantised : CELL_WIDTH;
};

export const geometryOf = (
  columns: number,
  rows: number,
  cellWidth: number = CELL_WIDTH,
  cellHeight: number = CELL_HEIGHT
): ChronoGeometry => {
  const plotWidth = Math.round(columns * cellWidth);
  const plotHeight = Math.round(rows * cellHeight);
  return {
    columns,
    rows,
    cellWidth,
    cellHeight,
    plotWidth,
    plotHeight,
    width: GUTTER_LEFT + plotWidth + GUTTER_RIGHT,
    height: GUTTER_TOP + plotHeight
  };
};

export interface CellHit {
  column: number;
  row: number;
}

export const hitTest = (
  offsetX: number,
  offsetY: number,
  geometry: ChronoGeometry
): CellHit | null => {
  const x = offsetX - GUTTER_LEFT;
  const y = offsetY - GUTTER_TOP;
  if (x < 0 || y < 0) {
    return null;
  }
  const column = Math.floor(x / geometry.cellWidth);
  const row = Math.floor(y / geometry.cellHeight);
  if (column < 0 || row < 0 || column >= geometry.columns || row >= geometry.rows) {
    return null;
  }
  return { column, row };
};

export const columnX = (column: number, cellWidth: number = CELL_WIDTH): number =>
  GUTTER_LEFT + column * cellWidth;

export const rowY = (row: number, cellHeight: number = CELL_HEIGHT): number =>
  GUTTER_TOP + row * cellHeight;

export const labelStride = (cellHeight: number = CELL_HEIGHT): number =>
  Math.max(1, Math.ceil(LABEL_MIN_GAP / cellHeight));

export interface YearTick {
  column: number;
  year: string;
}

export const yearTicks = (dates: readonly string[]): YearTick[] => {
  const ticks: YearTick[] = [];
  let seen: string | null = null;
  dates.forEach((date, column) => {
    const year = date.slice(0, 4);
    if (year.length === 0 || year === seen) {
      return;
    }
    seen = year;
    ticks.push({ column, year });
  });
  return ticks;
};
