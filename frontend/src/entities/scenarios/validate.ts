import type { ScenariosFile } from '@/entities/scenarios/types';
import { isAbsent, isArtifactMeta, isBool, isBoolOrNull, isNum, isNumArray, isNumOrNull, isRecord, isSafeArray, isStr, isStrArray, isStrOrNull } from '@/shared/api/guards';

const REGRET_PARTS = ['optimization', 'holdout'];

const isOptionalNum = (value: unknown): boolean => isAbsent(value) || isNum(value);

const isWorstRegret = (value: unknown): boolean =>
  isAbsent(value) ||
  (isRecord(value) &&
    isStr(value.scenario_id) &&
    isNum(value.value_rub) &&
    isStr(value.part) &&
    REGRET_PARTS.includes(value.part));

const isFinalNpv = (value: unknown): boolean =>
  isAbsent(value) ||
  (isRecord(value) && isNum(value.npv_rub) && isStr(value.run_id));

const CONSTRAINT_COUNTS = [
  'injection_limits',
  'liquid_limits',
  'production_floors',
  'watercut_limits',
  'well_outages',
  'infrastructure'
];

const isConstraintsSummary = (data: unknown): boolean =>
  isRecord(data) &&
  CONSTRAINT_COUNTS.every((key) => isNum(data[key])) &&
  isNumArray(data.years) &&
  isStrArray(data.outage_wells) &&
  isBool(data.empty);

const isPhysicsSkip = (data: unknown): boolean =>
  isRecord(data) &&
  isStr(data.invariant) &&
  isStr(data.reason) &&
  isStr(data.severity);

const isScenarioPhysics = (value: unknown): boolean =>
  isAbsent(value) ||
  (isRecord(value) &&
    isNum(value.total) &&
    isNum(value.evaluated_count) &&
    isStrArray(value.evaluated) &&
    isSafeArray(value.skipped) &&
    value.skipped.every(isPhysicsSkip) &&
    isNum(value.blocking_count) &&
    isNum(value.warning_count) &&
    isBool(value.complete) &&
    isBool(value.admissible) &&
    isStrArray(value.warning_invariants));

const isScenarioEntry = (data: unknown): boolean =>
  isRecord(data) &&
  isStr(data.id) &&
  isStr(data.config_hash) &&
  isBool(data.converged) &&
  isBool(data.self_consistent) &&
  isBool(data.is_submitted) &&
  isNumOrNull(data.npv_methodology) &&
  (isAbsent(data.run_validation_clean) || isBoolOrNull(data.run_validation_clean)) &&
  isConstraintsSummary(data.constraints) &&
  isOptionalNum(data.ood_score) &&
  isOptionalNum(data.ood_threshold) &&
  isOptionalNum(data.predicted_npv_rub) &&
  isOptionalNum(data.calibrated_npv_rub) &&
  isWorstRegret(data.worst_regret) &&
  isScenarioPhysics(data.physics) &&
  isFinalNpv(data.final_npv);

export const isScenariosFile = (data: unknown): data is ScenariosFile =>
  isRecord(data) &&
  isArtifactMeta(data.meta) &&
  isStrOrNull(data.submitted) &&
  isSafeArray(data.scenarios) &&
  data.scenarios.every(isScenarioEntry);
