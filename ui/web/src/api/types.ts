export interface GridSize {
  ni: number;
  nj: number;
  nk: number;
}

export interface LayerRange {
  id: number;
  k_min: number;
  k_max: number;
}

export interface WellPoint {
  id: string;
  i: number;
  j: number;
  completions: [number, number][];
  layers: number[];
}

export interface WellsFile {
  grid: GridSize;
  layers: LayerRange[];
  wells: WellPoint[];
}
