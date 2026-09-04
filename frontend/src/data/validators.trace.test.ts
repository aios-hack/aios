import { describe, expect, it } from 'vitest';
import { isTraceFile } from './validators';

const traceRecord = { rule: 'R4', decision: 'SET_RATE 124.9', inputs: { compensation: 1.29 } };

describe('isTraceFile', () => {
  it('accepts an empty object and a well-formed trace', () => {
    expect(isTraceFile({})).toBe(true);
    expect(isTraceFile({ '11': { '0': [] } })).toBe(true);
    expect(isTraceFile({ '11': { '0': [traceRecord] } })).toBe(true);
  });

  it('keeps the artifact metadata key out of the step scan', () => {
    expect(
      isTraceFile({
        __meta__: { kind: 'trace', provenance: 'model-z-base-run' },
        '11': { '0': [traceRecord] }
      })
    ).toBe(true);
  });

  it('rejects a non-object payload', () => {
    expect(isTraceFile(null)).toBe(false);
    expect(isTraceFile([])).toBe(false);
    expect(isTraceFile('trace')).toBe(false);
  });

  it('rejects step buckets that are not arrays of records', () => {
    expect(isTraceFile({ '11': { '0': 'SET_RATE' } })).toBe(false);
    expect(isTraceFile({ '11': [traceRecord] })).toBe(false);
  });

  it('rejects a record missing the fields the well card renders', () => {
    expect(isTraceFile({ '11': { '0': [{ rule: 'R4', decision: 'd' }] } })).toBe(false);
    expect(
      isTraceFile({ '11': { '0': [{ rule: 'R4', decision: 'd', inputs: { a: 'x' } }] } })
    ).toBe(false);
  });
});
