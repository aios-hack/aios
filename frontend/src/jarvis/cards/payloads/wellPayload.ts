import type { WellPayload } from '@/jarvis/cards/payloads/payloadTypes';
import { isNum, isRecord, isStr, numOrNull, sparkOf } from '@/jarvis/cards/payloads/payloadPrimitives';

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
