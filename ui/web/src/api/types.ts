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

export interface TimelineWellRow {
  well: string;
  availability: string;
  role: string;
  operating_status: string;
  setpoint: number;
  liquid_rate: number;
  injection_rate: number;
  bhp: number;
  watercut: number | null;
}

export interface TimelineFieldStats {
  production: number | null;
  injection: number | null;
  compensation: number | null;
  npv_cumulative: number;
  active_wells: number;
}

export interface TimelineStep {
  control_step: number;
  date: string;
  terminal: boolean;
  field: TimelineFieldStats;
  wells: TimelineWellRow[];
}

export interface TimelineFile {
  model: string;
  t0: string;
  n_control_dates: number;
  n_intervals: number;
  wells: string[];
  steps: TimelineStep[];
}
