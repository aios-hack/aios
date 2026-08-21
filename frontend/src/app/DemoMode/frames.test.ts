import { describe, expect, it } from 'vitest';
import type { DemoScriptFile } from '../../api/types';
import { isDemoScriptFile } from '../../data/validators';
import shipped from '../../../public/data/demo-script.json';
import { scriptFixture, timelineFixture, traceFixture } from './fixtures';
import { confirmEvent, resolveScript } from './frames';
import { DOC_SCENE_MODES, sceneModeOf } from './scenes';

const shippedScript = shipped as DemoScriptFile;

const TARGET_MS_MIN = 45000;
const TARGET_MS_MAX = 90000;

describe('demo scene names', () => {
  it('maps document scene names onto console scene modes through one table', () => {
    expect(sceneModeOf('chronomap')).toBe('chrono');
    expect(sceneModeOf('projection')).toBe('projection');
    expect(DOC_SCENE_MODES.chronomap).toBe('chrono');
  });

  it('rejects a scene name the console does not know', () => {
    expect(sceneModeOf('cinema')).toBeNull();
  });
});

describe('demo frame validation', () => {
  it('confirms a rule only when the trace holds it for that well and step', () => {
    const steps = timelineFixture.steps;
    expect(
      confirmEvent({ type: 'RULE_FIRED', well: '1', rule: 'R1' }, steps, traceFixture, 30)
    ).toBe(true);
    expect(
      confirmEvent({ type: 'RULE_FIRED', well: '1', rule: 'R4' }, steps, traceFixture, 30)
    ).toBe(false);
    expect(
      confirmEvent({ type: 'RULE_FIRED', well: '2', rule: 'R1' }, steps, traceFixture, 30)
    ).toBe(false);
  });

  it('confirms fund events only on a real change between neighbouring steps', () => {
    const steps = timelineFixture.steps;
    expect(
      confirmEvent({ type: 'COMMISSIONED', well: '3' }, steps, traceFixture, 10)
    ).toBe(true);
    expect(
      confirmEvent({ type: 'COMMISSIONED', well: '3' }, steps, traceFixture, 11)
    ).toBe(false);
    expect(confirmEvent({ type: 'ROLE_CHANGE', well: '2' }, steps, traceFixture, 20)).toBe(
      true
    );
    expect(confirmEvent({ type: 'SHUT', well: '1' }, steps, traceFixture, 20)).toBe(false);
  });

  it('drops an unconfirmed frame and logs it instead of showing it', () => {
    const script: DemoScriptFile = {
      frames: [
        ...scriptFixture.frames,
        {
          step: 5,
          scene: 'projection',
          well: '2',
          event: { type: 'RULE_FIRED', well: '2', rule: 'R9' },
          hold_ms: 40
        },
        { step: 5, scene: 'cinema', well: null, event: null, hold_ms: 40 },
        { step: 900, scene: 'projection', well: null, event: null, hold_ms: 40 }
      ]
    };
    const resolved = resolveScript(script, timelineFixture, traceFixture);
    expect(resolved.frames).toHaveLength(scriptFixture.frames.length);
    expect(resolved.skipped.map((frame) => frame.reason)).toEqual([
      'event',
      'scene',
      'step'
    ]);
  });

  it('sums the holds of the frames that survived validation', () => {
    const resolved = resolveScript(scriptFixture, timelineFixture, traceFixture);
    expect(resolved.totalMs).toBe(
      scriptFixture.frames.reduce((sum, frame) => sum + frame.hold_ms, 0)
    );
  });

  it('carries the step date and the cumulative npv of the step into the frame', () => {
    const resolved = resolveScript(scriptFixture, timelineFixture, traceFixture);
    const last = resolved.frames[resolved.frames.length - 1];
    expect(last.date).toBe(timelineFixture.steps[30].date);
    expect(last.npvCumulative).toBe(timelineFixture.steps[30].field.npv_cumulative);
  });
});

describe('shipped walkthrough', () => {
  it('passes the document validator', () => {
    expect(isDemoScriptFile(shippedScript)).toBe(true);
  });

  it('keeps the total hold inside the target duration of the defence', () => {
    const total = shippedScript.frames.reduce((sum, frame) => sum + frame.hold_ms, 0);
    expect(total).toBeGreaterThanOrEqual(TARGET_MS_MIN);
    expect(total).toBeLessThanOrEqual(TARGET_MS_MAX);
  });

  it('names only scenes the console knows', () => {
    const unknown = shippedScript.frames
      .map((frame) => frame.scene)
      .filter((scene) => sceneModeOf(scene) === null);
    expect(unknown).toEqual([]);
  });
});
