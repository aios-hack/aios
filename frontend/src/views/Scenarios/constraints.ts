import type { ConstraintsDoc, WellOutageDoc } from '../../api/types';

export type YearSection =
  | 'injection_limits'
  | 'liquid_limits'
  | 'production_floors'
  | 'watercut_limits';

export const YEAR_SECTIONS: YearSection[] = [
  'injection_limits',
  'liquid_limits',
  'production_floors',
  'watercut_limits'
];

export interface YearRow {
  key: string;
  year: string;
  value: string;
}

export interface OutageRow {
  key: string;
  well: string;
  from: string;
  to: string;
}

export interface PairRow {
  key: string;
  name: string;
  value: string;
}

export interface EditorState {
  sections: Record<YearSection, YearRow[]>;
  outages: OutageRow[];
  infrastructure: PairRow[];
}

export interface FieldError {
  key: string;
  field: string;
  messageKey: string;
  params?: Record<string, string | number>;
}

export const emptyEditorState = (): EditorState => ({
  sections: {
    injection_limits: [],
    liquid_limits: [],
    production_floors: [],
    watercut_limits: []
  },
  outages: [],
  infrastructure: []
});

let counter = 0;
export const nextKey = (prefix: string): string => `${prefix}-${(counter += 1)}`;

const isBlank = (value: string): boolean => value.trim() === '';

const parseYear = (raw: string): number | null => {
  const text = raw.trim();
  return /^-?\d+$/.test(text) ? Number(text) : null;
};

const parseAmount = (raw: string): number | null => {
  const text = raw.trim().replace(',', '.');
  if (!/^-?\d+(\.\d+)?$/.test(text)) {
    return null;
  }
  const value = Number(text);
  return Number.isFinite(value) ? value : null;
};

const validateYearRows = (
  section: YearSection,
  rows: YearRow[],
  errors: FieldError[]
): void => {
  const seen = new Map<number, string>();
  for (const row of rows) {
    const year = parseYear(row.year);
    if (year === null) {
      errors.push({ key: row.key, field: 'year', messageKey: 'error.year' });
    } else if (seen.has(year)) {
      errors.push({ key: row.key, field: 'year', messageKey: 'error.duplicateYear', params: { year } });
    } else {
      seen.set(year, row.key);
    }
    const value = parseAmount(row.value);
    if (value === null) {
      errors.push({ key: row.key, field: 'value', messageKey: 'error.number' });
      continue;
    }
    if (value < 0) {
      errors.push({ key: row.key, field: 'value', messageKey: 'error.negative' });
      continue;
    }
    if (section === 'watercut_limits' && value > 1) {
      errors.push({ key: row.key, field: 'value', messageKey: 'error.watercut' });
    }
  }
};

const parseStep = (raw: string): number | null => {
  const text = raw.trim();
  return /^-?\d+$/.test(text) ? Number(text) : null;
};

const validateOutages = (
  rows: OutageRow[],
  nIntervals: number,
  errors: FieldError[]
): void => {
  for (const row of rows) {
    if (isBlank(row.well)) {
      errors.push({ key: row.key, field: 'well', messageKey: 'error.well' });
    }
    const from = parseStep(row.from);
    const to = parseStep(row.to);
    const last = nIntervals - 1;
    if (from === null) {
      errors.push({ key: row.key, field: 'from', messageKey: 'error.step' });
    } else if (from < 0 || from > last) {
      errors.push({ key: row.key, field: 'from', messageKey: 'error.horizon', params: { last } });
    }
    if (to === null) {
      errors.push({ key: row.key, field: 'to', messageKey: 'error.step' });
    } else if (to < 0 || to > last) {
      errors.push({ key: row.key, field: 'to', messageKey: 'error.horizon', params: { last } });
    }
    if (from !== null && to !== null && from > to) {
      errors.push({ key: row.key, field: 'to', messageKey: 'error.range' });
    }
  }
};

const validatePairs = (rows: PairRow[], errors: FieldError[]): void => {
  const seen = new Set<string>();
  for (const row of rows) {
    const name = row.name.trim();
    if (name === '') {
      errors.push({ key: row.key, field: 'name', messageKey: 'error.pairName' });
      continue;
    }
    if (seen.has(name)) {
      errors.push({ key: row.key, field: 'name', messageKey: 'error.duplicatePair', params: { name } });
    }
    seen.add(name);
  }
};

export const validateEditor = (state: EditorState, nIntervals: number): FieldError[] => {
  const errors: FieldError[] = [];
  for (const section of YEAR_SECTIONS) {
    validateYearRows(section, state.sections[section], errors);
  }
  validateOutages(state.outages, nIntervals, errors);
  validatePairs(state.infrastructure, errors);
  return errors;
};

const yearMap = (rows: YearRow[]): Record<string, number> => {
  const result: Record<string, number> = {};
  for (const row of rows) {
    const year = parseYear(row.year);
    const value = parseAmount(row.value);
    if (year !== null && value !== null) {
      result[String(year)] = value;
    }
  }
  return result;
};

export const toDocument = (state: EditorState): ConstraintsDoc => {
  const outages: WellOutageDoc[] = [];
  for (const row of state.outages) {
    const from = parseStep(row.from);
    const to = parseStep(row.to);
    if (!isBlank(row.well) && from !== null && to !== null) {
      outages.push({ well: row.well.trim(), control_step_from: from, control_step_to: to });
    }
  }
  const infrastructure: Record<string, string | number> = {};
  for (const row of state.infrastructure) {
    const name = row.name.trim();
    if (name === '') {
      continue;
    }
    const numeric = parseAmount(row.value);
    infrastructure[name] = numeric === null ? row.value.trim() : numeric;
  }
  return {
    injection_limits: yearMap(state.sections.injection_limits),
    liquid_limits: yearMap(state.sections.liquid_limits),
    production_floors: yearMap(state.sections.production_floors),
    watercut_limits: yearMap(state.sections.watercut_limits),
    well_outages: outages,
    infrastructure
  };
};
