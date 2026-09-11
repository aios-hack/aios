export const INFRASTRUCTURE_PARAMETERS = [
  { key: 'water_reinjection_fraction', min: 0, max: 1 },
  { key: 'water_reinjection_lag_steps', min: 0, integer: true },
  { key: 'external_water_m3_per_day', min: 0 },
  { key: 'compensation_min', min: 0 },
  { key: 'compensation_max', min: 0 },
  { key: 'compensation_enforcement', choices: ['diagnostic', 'hard'] },
  { key: 'compensation_scope', choices: ['field', 'groups', 'field_and_groups'] }
] as const;
