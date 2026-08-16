import type { ConstraintsDoc } from '../../api/types';
import {
  YEAR_SECTIONS,
  emptyEditorState,
  nextKey,
  type EditorState,
  type YearSection
} from './constraints';

export interface ParseFailure {
  messageKey: string;
  params?: Record<string, string | number>;
}

export type ParseResult =
  | { ok: true; state: EditorState; document: ConstraintsDoc }
  | { ok: false; error: ParseFailure };

const KNOWN_SECTIONS = new Set<string>([
  ...YEAR_SECTIONS,
  'well_outages',
  'infrastructure'
]);

const isPlainObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

const fail = (messageKey: string, params?: Record<string, string | number>): ParseResult => ({
  ok: false,
  error: { messageKey, params }
});

const readYearSection = (
  raw: unknown,
  section: YearSection,
  state: EditorState
): ParseFailure | null => {
  if (raw === undefined) {
    return null;
  }
  if (!isPlainObject(raw)) {
    return { messageKey: 'load.error.sectionShape', params: { section } };
  }
  for (const [year, value] of Object.entries(raw)) {
    if (!/^-?\d+$/.test(year.trim())) {
      return { messageKey: 'load.error.year', params: { section, year } };
    }
    if (typeof value !== 'number' || !Number.isFinite(value)) {
      return { messageKey: 'load.error.number', params: { section, year } };
    }
    if (value < 0) {
      return { messageKey: 'load.error.negative', params: { section, year } };
    }
    if (section === 'watercut_limits' && value > 1) {
      return { messageKey: 'load.error.watercut', params: { year, value } };
    }
    state.sections[section].push({
      key: nextKey(section),
      year: year.trim(),
      value: String(value)
    });
  }
  return null;
};

const readOutages = (
  raw: unknown,
  nIntervals: number,
  state: EditorState
): ParseFailure | null => {
  if (raw === undefined) {
    return null;
  }
  if (!Array.isArray(raw)) {
    return { messageKey: 'load.error.outagesShape' };
  }
  const last = nIntervals - 1;
  for (let index = 0; index < raw.length; index += 1) {
    const item = raw[index];
    if (!isPlainObject(item)) {
      return { messageKey: 'load.error.outageShape', params: { index } };
    }
    const { well, control_step_from: from, control_step_to: to } = item;
    if (typeof well !== 'string' || well.trim() === '') {
      return { messageKey: 'load.error.outageWell', params: { index } };
    }
    if (!Number.isInteger(from) || !Number.isInteger(to)) {
      return { messageKey: 'load.error.outageStep', params: { index } };
    }
    const stepFrom = from as number;
    const stepTo = to as number;
    if (stepFrom < 0 || stepFrom > last || stepTo < 0 || stepTo > last) {
      return { messageKey: 'load.error.outageHorizon', params: { index, last } };
    }
    if (stepFrom > stepTo) {
      return { messageKey: 'load.error.outageRange', params: { index } };
    }
    state.outages.push({
      key: nextKey('outage'),
      well: well.trim(),
      from: String(stepFrom),
      to: String(stepTo)
    });
  }
  return null;
};

const readInfrastructure = (raw: unknown, state: EditorState): ParseFailure | null => {
  if (raw === undefined) {
    return null;
  }
  if (!isPlainObject(raw)) {
    return { messageKey: 'load.error.infrastructureShape' };
  }
  for (const [name, value] of Object.entries(raw)) {
    if (typeof value !== 'string' && typeof value !== 'number') {
      return { messageKey: 'load.error.infrastructureValue', params: { name } };
    }
    state.infrastructure.push({
      key: nextKey('pair'),
      name,
      value: String(value)
    });
  }
  return null;
};

export const parseDocument = (raw: unknown, nIntervals: number): ParseResult => {
  if (!isPlainObject(raw)) {
    return fail('load.error.root');
  }
  const unknown = Object.keys(raw).filter((key) => !KNOWN_SECTIONS.has(key));
  if (unknown.length > 0) {
    return fail('load.error.unknownSection', { sections: unknown.sort().join(', ') });
  }
  const state = emptyEditorState();
  for (const section of YEAR_SECTIONS) {
    const failure = readYearSection(raw[section], section, state);
    if (failure) {
      return { ok: false, error: failure };
    }
  }
  const outageFailure = readOutages(raw.well_outages, nIntervals, state);
  if (outageFailure) {
    return { ok: false, error: outageFailure };
  }
  const infraFailure = readInfrastructure(raw.infrastructure, state);
  if (infraFailure) {
    return { ok: false, error: infraFailure };
  }
  return { ok: true, state, document: raw as unknown as ConstraintsDoc };
};

export const parseJsonText = (text: string, nIntervals: number): ParseResult => {
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    return fail('load.error.json');
  }
  return parseDocument(data, nIntervals);
};
