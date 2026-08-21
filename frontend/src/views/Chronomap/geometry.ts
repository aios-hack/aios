export const CELL_WIDTH = 4;
export const CELL_HEIGHT = 6;
export const GUTTER_LEFT = 58;
export const GUTTER_TOP = 18;
export const LABEL_MIN_GAP = 11;

export interface ChronoGeometry {
  columns: number;
  rows: number;
  plotWidth: number;
  plotHeight: number;
  width: number;
  height: number;
}

export const geometryOf = (columns: number, rows: number): ChronoGeometry => {
  const plotWidth = columns * CELL_WIDTH;
  const plotHeight = rows * CELL_HEIGHT;
  return {
    columns,
    rows,
    plotWidth,
    plotHeight,
    width: GUTTER_LEFT + plotWidth,
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
  const column = Math.floor(x / CELL_WIDTH);
  const row = Math.floor(y / CELL_HEIGHT);
  if (column < 0 || row < 0 || column >= geometry.columns || row >= geometry.rows) {
    return null;
  }
  return { column, row };
};

export const columnX = (column: number): number => GUTTER_LEFT + column * CELL_WIDTH;

export const rowY = (row: number): number => GUTTER_TOP + row * CELL_HEIGHT;

export const labelStride = (): number =>
  Math.max(1, Math.ceil(LABEL_MIN_GAP / CELL_HEIGHT));

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
