import type {
  ComparePayload,
  CompareSide,
  ErrorPayload,
  EventStripPayload,
  FieldMapPayload,
  MetricPayload,
  PatternPayload,
  SeriesPayload,
  WellListPayload,
  WellPayload
} from './payloadTypes';
import {
  isNum,
  isRecord,
  isStr,
  list,
  numOrNull,
  numbersOf,
  sparkOf,
  strOrNull
} from './payloadPrimitives';

export const readMetric = (payload: unknown): MetricPayload | null => {
  if (!isRecord(payload) || !isStr(payload.label) || !isNum(payload.value)) {
    return null;
  }
  return {
    id: isStr(payload.id) ? payload.id : payload.label,
    label: payload.label,
    value: payload.value,
    unit: isStr(payload.unit) ? payload.unit : '',
    delta: numOrNull(payload.delta),
    spark: sparkOf(payload.spark)
  };
};

export const readMetrics = (payload: unknown): MetricPayload[] => {
  if (isRecord(payload) && Array.isArray(payload.metrics)) {
    return payload.metrics
      .map((entry) => readMetric(entry))
      .filter((entry): entry is MetricPayload => entry !== null);
  }
  if (Array.isArray(payload)) {
    return payload
      .map((entry) => readMetric(entry))
      .filter((entry): entry is MetricPayload => entry !== null);
  }
  const single = readMetric(payload);
  return single === null ? [] : [single];
};

export const readWell = (payload: unknown): WellPayload | null => {
  if (!isRecord(payload) || !isStr(payload.well)) {
    return null;
  }
  if (!isNum(payload.liquid_rate) || !isNum(payload.injection_rate)) {
    return null;
  }
  return {
    well: payload.well,
    role: isStr(payload.role) ? payload.role : '',
    availability: isStr(payload.availability) ? payload.availability : '',
    operating_status: isStr(payload.operating_status) ? payload.operating_status : '',
    liquid_rate: payload.liquid_rate,
    injection_rate: payload.injection_rate,
    watercut: numOrNull(payload.watercut),
    bhp: isNum(payload.bhp) ? payload.bhp : 0,
    setpoint: isNum(payload.setpoint) ? payload.setpoint : 0,
    npv: numOrNull(payload.npv),
    spark: sparkOf(payload.spark)
  };
};

export const readWellList = (payload: unknown): WellListPayload | null => {
  if (!isRecord(payload)) {
    return null;
  }
  const rows = list(payload.rows)
    .filter((row): row is Record<string, unknown> => isRecord(row) && isStr(row.well))
    .filter((row) => isNum(row.value))
    .map((row) => ({
      well: row.well as string,
      value: row.value as number,
      share: numOrNull(row.share)
    }));
  if (rows.length === 0) {
    return null;
  }
  return {
    by: isStr(payload.by) ? payload.by : '',
    unit: isStr(payload.unit) ? payload.unit : '',
    order: isStr(payload.order) ? payload.order : 'desc',
    rows
  };
};

export const readSeries = (payload: unknown): SeriesPayload | null => {
  if (!isRecord(payload)) {
    return null;
  }
  const rows = list(payload.rows)
    .filter((row): row is Record<string, unknown> => isRecord(row) && isNum(row.step))
    .map((row) => ({
      step: row.step as number,
      date: isStr(row.date) ? row.date : '',
      value: numOrNull(row.value)
    }));
  if (rows.length === 0) {
    return null;
  }
  const range = list(payload.window);
  return {
    metric: isStr(payload.metric) ? payload.metric : '',
    unit: isStr(payload.unit) ? payload.unit : '',
    rows,
    window: range.length === 2 && isNum(range[0]) && isNum(range[1]) ? [range[0], range[1]] : null
  };
};

const compareSide = (value: unknown): CompareSide | null => {
  if (!isRecord(value) || !isStr(value.id)) {
    return null;
  }
  return {
    id: value.id,
    npv: numOrNull(value.npv),
    status: isStr(value.status) ? value.status : '',
    constraints: isNum(value.constraints) ? value.constraints : 0
  };
};

export const readCompare = (payload: unknown): ComparePayload | null => {
  if (!isRecord(payload)) {
    return null;
  }
  const a = compareSide(payload.a);
  const b = compareSide(payload.b);
  if (a === null || b === null || !isNum(payload.delta_npv)) {
    return null;
  }
  return {
    a,
    b,
    delta_npv: payload.delta_npv,
    top_diff_wells: list(payload.top_diff_wells)
      .filter((row): row is Record<string, unknown> => isRecord(row) && isStr(row.well))
      .filter((row) => isNum(row.delta))
      .map((row) => ({ well: row.well as string, delta: row.delta as number }))
  };
};

export const readEventStrip = (payload: unknown): EventStripPayload | null => {
  if (!isRecord(payload)) {
    return null;
  }
  return {
    from_step: isNum(payload.from_step) ? payload.from_step : 0,
    to_step: isNum(payload.to_step) ? payload.to_step : 0,
    events: list(payload.events)
      .filter((row): row is Record<string, unknown> => isRecord(row) && isNum(row.step))
      .filter((row) => isStr(row.well) && isStr(row.type))
      .map((row) => ({
        step: row.step as number,
        date: isStr(row.date) ? row.date : '',
        well: row.well as string,
        type: row.type as string
      }))
  };
};

export const readFieldMap = (payload: unknown): FieldMapPayload | null => {
  if (!isRecord(payload)) {
    return null;
  }
  const edges = list(payload.edges)
    .filter((edge): edge is Record<string, unknown> => isRecord(edge))
    .filter((edge) => isStr(edge.injector) && isStr(edge.producer) && isNum(edge.weight))
    .map((edge) => ({
      injector: edge.injector as string,
      producer: edge.producer as string,
      weight: edge.weight as number
    }));
  return {
    focus: list(payload.focus).filter(isStr),
    highlight: list(payload.highlight).filter(isStr),
    edges,
    layer: strOrNull(payload.layer)
  };
};

export const readPattern = (payload: unknown): PatternPayload | null => {
  if (!isRecord(payload) || !isStr(payload.pattern_id) || !isStr(payload.well)) {
    return null;
  }
  const range = isRecord(payload.window) ? payload.window : {};
  return {
    pattern_id: payload.pattern_id,
    name: isStr(payload.name) ? payload.name : payload.pattern_id,
    well: payload.well,
    severity: isStr(payload.severity) ? payload.severity : '',
    window: {
      from_step: isNum(range.from_step) ? range.from_step : 0,
      to_step: isNum(range.to_step) ? range.to_step : 0
    },
    inputs: numbersOf(payload.inputs)
  };
};

export const readError = (payload: unknown): ErrorPayload => {
  if (!isRecord(payload)) {
    return { code: 'unknown', tool: null, message: '' };
  }
  return {
    code: isStr(payload.code) ? payload.code : 'unknown',
    tool: strOrNull(payload.tool),
    message: isStr(payload.message) ? payload.message : ''
  };
};

export * from './knowledgePayloads';
export * from './rulePayloads';
export type * from './payloadTypes';
