import type {
  ConstraintRow,
  ConstraintsPayload,
  CouncilLevel,
  CouncilPayload,
  PhysicsCheck,
  PhysicsPayload,
  RunListPayload,
  RunPayload,
  RunRow
} from './systemTypes';
import { boolOrNull, scalar } from './scalars';
import { isNum, isRecord, isStr, list, numOrNull, strOrNull } from './payloadPrimitives';

const runRow = (value: unknown): RunRow | null => {
  if (!isRecord(value) || !isStr(value.run_id)) {
    return null;
  }
  return {
    run_id: value.run_id,
    ts: isStr(value.ts) ? value.ts : '',
    status: strOrNull(value.status),
    predicted_npv: numOrNull(value.predicted_npv),
    verified_npv: numOrNull(value.verified_npv),
    sound: boolOrNull(value.sound),
    strategy: strOrNull(value.strategy),
    seed: numOrNull(value.seed)
  };
};

export const readRunList = (payload: unknown): RunListPayload | null => {
  if (!isRecord(payload)) {
    return null;
  }
  const rows = list(payload.rows)
    .map(runRow)
    .filter((row): row is RunRow => row !== null);
  if (rows.length === 0) {
    return null;
  }
  return { rows, total: isNum(payload.total) ? payload.total : rows.length };
};

const physicsCheck = (value: unknown): PhysicsCheck | null => {
  if (!isRecord(value)) {
    return null;
  }
  const id = strOrNull(value.id);
  if (id === null) {
    return null;
  }
  return { id, status: strOrNull(value.status) ?? 'ok', detail: strOrNull(value.detail) };
};

export const readPhysics = (payload: unknown): PhysicsPayload | null => {
  if (!isRecord(payload)) {
    return null;
  }
  return {
    run_id: isStr(payload.run_id) ? payload.run_id : '',
    admissible: boolOrNull(payload.admissible),
    blocking: numOrNull(payload.blocking),
    warnings: numOrNull(payload.warnings),
    checks: list(payload.checks)
      .map(physicsCheck)
      .filter((check): check is PhysicsCheck => check !== null)
  };
};

export const readRun = (payload: unknown): RunPayload | null => {
  const row = runRow(payload);
  if (row === null || !isRecord(payload)) {
    return null;
  }
  return {
    ...row,
    schedule_hash: strOrNull(payload.schedule_hash),
    claimed_npv: numOrNull(payload.claimed_npv_rub),
    has_submission: payload.has_submission === true,
    violations: list(payload.violations)
      .filter(isRecord)
      .map((entry) => ({
        kind: strOrNull(entry.kind) ?? '',
        detail: strOrNull(entry.detail) ?? ''
      })),
    physics: readPhysics(payload.physics)
  };
};

const constraintRow = (value: unknown): ConstraintRow | null => {
  if (!isRecord(value) || !isStr(value.key)) {
    return null;
  }
  return {
    key: value.key,
    group: strOrNull(value.group),
    value: scalar(value.value),
    unit: strOrNull(value.unit),
    source: strOrNull(value.source),
    empty: value.empty === true
  };
};

export const readConstraints = (payload: unknown): ConstraintsPayload | null => {
  if (!isRecord(payload)) {
    return null;
  }
  const items = list(payload.items)
    .map(constraintRow)
    .filter((row): row is ConstraintRow => row !== null);
  if (items.length === 0) {
    return null;
  }
  return { case: isStr(payload.case) ? payload.case : '', items };
};

const councilLevel = (value: unknown): CouncilLevel | null => {
  if (!isRecord(value) || !isStr(value.agent)) {
    return null;
  }
  return {
    rank: isNum(value.rank) ? value.rank : 0,
    agent: value.agent,
    level: strOrNull(value.level),
    verdict: strOrNull(value.verdict) ?? '',
    bounds: list(value.bounds).filter(isNum),
    decisions: list(value.decisions).length
  };
};

export const readCouncil = (payload: unknown): CouncilPayload | null => {
  if (!isRecord(payload) || !isNum(payload.step)) {
    return null;
  }
  const levels = list(payload.levels)
    .map(councilLevel)
    .filter((level): level is CouncilLevel => level !== null)
    .sort((a, b) => a.rank - b.rank);
  if (levels.length === 0) {
    return null;
  }
  const outcome = isRecord(payload.outcome) ? payload.outcome : {};
  return {
    step: payload.step,
    date: strOrNull(payload.date),
    group: strOrNull(payload.group),
    agents_fired: list(payload.agents_fired).filter(isStr),
    levels,
    outcome: {
      well: strOrNull(outcome.well),
      action: strOrNull(outcome.action) ?? strOrNull(outcome.decision),
      rule: strOrNull(outcome.rule)
    }
  };
};
