import type { SphereState } from '@/jarvis/sphere/lib/sphereState';
import { clamp01 } from '@/shared/lib/math/clamp';

export const MAX_BOLTS = 4;
export const BOLT_AFTERGLOW_MS = 600;
export const AUDIO_BOLT_COOLDOWN_MS = 400;
export const LISTEN_AUDIO_THRESHOLD = 0.45;
export const SPEAK_AUDIO_THRESHOLD = 0.35;

export interface BoltPlan {
  gapMinMs: number;
  gapMaxMs: number;
  countMin: number;
  countMax: number;
  durationMinMs: number;
  durationMaxMs: number;
  audioThreshold: number | null;
}

const PLANS: Record<SphereState, BoltPlan> = {
  idle: {
    gapMinMs: 5000,
    gapMaxMs: 11000,
    countMin: 1,
    countMax: 1,
    durationMinMs: 320,
    durationMaxMs: 480,
    audioThreshold: null
  },
  hover: {
    gapMinMs: 2500,
    gapMaxMs: 5000,
    countMin: 1,
    countMax: 2,
    durationMinMs: 320,
    durationMaxMs: 480,
    audioThreshold: null
  },
  listening: {
    gapMinMs: AUDIO_BOLT_COOLDOWN_MS,
    gapMaxMs: AUDIO_BOLT_COOLDOWN_MS,
    countMin: 1,
    countMax: 1,
    durationMinMs: 260,
    durationMaxMs: 260,
    audioThreshold: LISTEN_AUDIO_THRESHOLD
  },
  thinking: {
    gapMinMs: 1200,
    gapMaxMs: 2400,
    countMin: 1,
    countMax: 3,
    durationMinMs: 240,
    durationMaxMs: 360,
    audioThreshold: null
  },
  speaking: {
    gapMinMs: AUDIO_BOLT_COOLDOWN_MS,
    gapMaxMs: AUDIO_BOLT_COOLDOWN_MS,
    countMin: 1,
    countMax: 2,
    durationMinMs: 220,
    durationMaxMs: 220,
    audioThreshold: SPEAK_AUDIO_THRESHOLD
  },
  error: {
    gapMinMs: Number.POSITIVE_INFINITY,
    gapMaxMs: Number.POSITIVE_INFINITY,
    countMin: 0,
    countMax: 0,
    durationMinMs: 0,
    durationMaxMs: 0,
    audioThreshold: null
  }
};

export const boltPlanOf = (state: SphereState): BoltPlan => PLANS[state];

const span = (min: number, max: number, random: number): number =>
  min + (max - min) * clamp01(random);

export const boltGapOf = (state: SphereState, random: number): number => {
  const plan = PLANS[state];
  return span(plan.gapMinMs, plan.gapMaxMs, random);
};

export const boltCountOf = (state: SphereState, random: number): number => {
  const plan = PLANS[state];
  return Math.round(span(plan.countMin, plan.countMax, random));
};

export const boltDurationOf = (state: SphereState, random: number): number => {
  const plan = PLANS[state];
  return span(plan.durationMinMs, plan.durationMaxMs, random);
};

export interface Bolt {
  seed: number;
  startMs: number;
  durationMs: number;
  strength: number;
}

export interface BoltField {
  bolts: Bolt[];
  nextAtMs: number;
  lastAudioAtMs: number;
  audioArmed: boolean;
}

export const emptyBolts = (nowMs: number): BoltField => ({
  bolts: [],
  nextAtMs: nowMs + boltGapOf('idle', Math.random()),
  lastAudioAtMs: -Infinity,
  audioArmed: true
});

const spawn = (
  field: BoltField,
  state: SphereState,
  nowMs: number,
  random: () => number
): void => {
  const count = boltCountOf(state, random());
  for (let i = 0; i < count; i += 1) {
    field.bolts.push({
      seed: random() * 1000,
      startMs: nowMs + i * 60,
      durationMs: boltDurationOf(state, random()),
      strength: 0.7 + 0.3 * random()
    });
  }
  while (field.bolts.length > MAX_BOLTS) {
    field.bolts.shift();
  }
};

export const stepBolts = (
  field: BoltField,
  state: SphereState,
  audio: number,
  nowMs: number,
  random: () => number = Math.random
): BoltField => {
  const plan = PLANS[state];
  field.bolts = field.bolts.filter(
    (bolt) => nowMs - bolt.startMs < bolt.durationMs + BOLT_AFTERGLOW_MS
  );
  if (plan.countMax === 0) {
    field.nextAtMs = nowMs + boltGapOf(state, random());
    return field;
  }
  if (plan.audioThreshold !== null) {
    const loud = audio >= plan.audioThreshold;
    const ready = nowMs - field.lastAudioAtMs >= AUDIO_BOLT_COOLDOWN_MS;
    if (loud && ready && field.audioArmed) {
      spawn(field, state, nowMs, random);
      field.lastAudioAtMs = nowMs;
      field.audioArmed = false;
    }
    if (!loud) {
      field.audioArmed = true;
    }
    field.nextAtMs = nowMs + boltGapOf(state, random());
    return field;
  }
  field.audioArmed = true;
  if (nowMs >= field.nextAtMs) {
    spawn(field, state, nowMs, random);
    field.nextAtMs = nowMs + boltGapOf(state, random());
  }
  return field;
};

export const packBolts = (field: BoltField, nowMs: number): Float32Array => {
  const data = new Float32Array(MAX_BOLTS * 4);
  const visible = field.bolts.slice(-MAX_BOLTS);
  for (let i = 0; i < visible.length; i += 1) {
    const bolt = visible[i];
    const age = nowMs - bolt.startMs;
    const total = bolt.durationMs + BOLT_AFTERGLOW_MS;
    if (age < 0 || age > total) {
      continue;
    }
    const life = age <= bolt.durationMs ? 1 : 1 - (age - bolt.durationMs) / BOLT_AFTERGLOW_MS;
    const rise = Math.min(1, age / Math.max(bolt.durationMs * 0.25, 1));
    data[i * 4] = bolt.seed;
    data[i * 4 + 1] = Math.min(1, age / Math.max(bolt.durationMs, 1));
    data[i * 4 + 2] = bolt.durationMs / 1000;
    data[i * 4 + 3] = bolt.strength * life * rise;
  }
  return data;
};
