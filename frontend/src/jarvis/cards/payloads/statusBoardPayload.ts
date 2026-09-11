import type { StatusBoardPayload } from '@/jarvis/cards/payloads/systemTypes';
import { boolOrNull } from '@/jarvis/cards/payloads/scalars';
import { isNum, isRecord, isStr, list, numOrNull, strOrNull } from '@/jarvis/cards/payloads/payloadPrimitives';

export const readStatusBoard = (payload: unknown): StatusBoardPayload | null => {
  if (!isRecord(payload)) {
    return null;
  }
  const champion = isRecord(payload.champion) ? payload.champion : {};
  const last = isRecord(payload.last_run) ? payload.last_run : {};
  return {
    champion: {
      recorded: champion.recorded === true,
      npv: numOrNull(champion.opm_npv_rub),
      sound: boolOrNull(champion.sound),
      ood: numOrNull(champion.ood_score),
      reason: strOrNull(champion.reason)
    },
    last_run: {
      recorded: last.recorded === true,
      run_id: strOrNull(last.run_id),
      status: strOrNull(last.status),
      verified_npv: numOrNull(last.verified_npv),
      predicted_npv: numOrNull(last.predicted_npv),
      reason: strOrNull(last.reason)
    },
    scenario: isStr(payload.scenario) ? payload.scenario : '',
    step: isNum(payload.step) ? payload.step : 0,
    date: strOrNull(payload.date),
    data: isStr(payload.data) ? payload.data : '',
    alerts: list(payload.alerts)
      .filter(isRecord)
      .map((row) => ({
        pattern: strOrNull(row.pattern),
        name: strOrNull(row.name),
        well: strOrNull(row.well),
        severity: strOrNull(row.severity),
        step: numOrNull(row.step)
      }))
  };
};
