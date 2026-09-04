import { describe, expect, it } from 'vitest';
import type { TraceRecord } from '../../api/types';
import type { JarvisAskContext, JarvisCard } from '../transport/events';
import {
  allowedNumbers,
  explainEvents,
  factsOf,
  guardCaption,
  unsupportedNumbers,
  NO_TRACE_ENTRY,
  type ExplainFact
} from './explainScene';

const context: JarvisAskContext = {
  scenario: 'whatif-injection-cut',
  step: 10,
  date: '2007-11-01',
  selected_well: '13',
  workspace: 'decisions',
  view: 'council'
};

const record: TraceRecord = {
  rule: 'R1',
  inputs: { liquid_rate: 112.9, watercut: 0.614 },
  decision: 'SET_LRAT 112.9'
};

const ruleName = (rule: string) => `name-${rule}`;

const request = (records: TraceRecord[], caption: (facts: ExplainFact[]) => string) => ({
  well: '13',
  step: 10,
  date: '2007-11-01',
  records,
  context,
  provenance: 'trace',
  question: 'why',
  ruleName,
  caption,
  noEntryTitle: 'no entry',
  noEntryMessage: 'the journal holds no record for well 13',
  cardTitle: (rule: string, well: string) => `${rule} ${well}`
});

const cardsOf = (events: ReturnType<typeof explainEvents>): JarvisCard[] =>
  events.filter((event) => event.type === 'card').map((event) => event.card);

describe('factsOf reads only recorded journal facts', () => {
  it('keeps the rule, inputs and decision exactly as recorded', () => {
    const facts = factsOf([record], ruleName);
    expect(facts).toHaveLength(1);
    expect(facts[0].rule).toBe('R1');
    expect(facts[0].inputs).toEqual({ liquid_rate: 112.9, watercut: 0.614 });
    expect(facts[0].decision).toBe('SET_LRAT 112.9');
  });

  it('drops non-finite inputs rather than substituting a value', () => {
    const facts = factsOf(
      [{ rule: 'R1', inputs: { a: Number.NaN, b: 2 }, decision: 'SHUT' } as TraceRecord],
      ruleName
    );
    expect(facts[0].inputs).toEqual({ b: 2 });
  });

  it('drops a record with no rule or no decision', () => {
    expect(
      factsOf([{ rule: '', inputs: {}, decision: 'SHUT' } as TraceRecord], ruleName)
    ).toHaveLength(0);
    expect(
      factsOf([{ rule: 'R1', inputs: {}, decision: '' } as TraceRecord], ruleName)
    ).toHaveLength(0);
  });
});

describe('the provenance guard admits only numbers found in the trace', () => {
  const facts = factsOf([record], ruleName);

  it('collects the recorded inputs and the numbers of the decision', () => {
    const allowed = allowedNumbers(facts);
    expect(allowed).toContain(112.9);
    expect(allowed).toContain(0.614);
  });

  it('passes a caption that only quotes recorded numbers', () => {
    const guarded = guardCaption('Дебит 112.9, обводнённость 0.614.', facts);
    expect(guarded.dropped).toEqual([]);
    expect(guarded.text).toBe('Дебит 112.9, обводнённость 0.614.');
  });

  it('admits a percentage form of a recorded fraction', () => {
    expect(unsupportedNumbers('обводнённость 61.4', allowedNumbers(facts))).toEqual([]);
  });

  it('cuts a number that is absent from the trace', () => {
    const guarded = guardCaption('ЧДД вырос на 999999 рублей.', facts);
    expect(guarded.dropped).toEqual(['999999']);
    expect(guarded.text).not.toContain('999999');
  });

  it('cuts a plausible but unrecorded number', () => {
    expect(unsupportedNumbers('дебит 113.4', allowedNumbers(facts))).toEqual(['113.4']);
  });

  it('does not treat a date or a rule label as a number', () => {
    expect(unsupportedNumbers('R1 на 2007-11-01 по скважине 13', allowedNumbers(facts))).toEqual(
      []
    );
  });

  it('reports guarded even when nothing was cut', () => {
    expect(guardCaption('Решение записано.', facts).guarded).toBe(true);
  });
});

describe('explainEvents builds a scene from the journal', () => {
  it('emits a scene, a rule card per record, a caption and done', () => {
    const events = explainEvents(request([record], () => 'Решение записано.'));
    expect(events[0].type).toBe('scene');
    expect(events.at(-1)).toMatchObject({ type: 'done' });
    const cards = cardsOf(events);
    expect(cards).toHaveLength(1);
    expect(cards[0].type).toBe('rule');
    expect(cards[0].provenance).toBe('trace');
  });

  it('puts only recorded numbers into the card payload', () => {
    const events = explainEvents(request([record], () => 'Решение записано.'));
    const payload = cardsOf(events)[0].payload as {
      inputs: Record<string, number>;
      decision: string;
      source: string;
    };
    expect(payload.inputs).toEqual({ liquid_rate: 112.9, watercut: 0.614 });
    expect(payload.decision).toBe('SET_LRAT 112.9');
    expect(payload.source).toBe('trace.json');
  });

  it('carries an action back to the rules view of the console', () => {
    const events = explainEvents(request([record], () => 'Решение записано.'));
    expect(cardsOf(events)[0].action).toMatchObject({
      workspace: 'decisions',
      view: 'rules',
      well: '13',
      step: 10,
      scenario: 'whatif-injection-cut'
    });
  });

  it('guards the caption and warns when a number is cut', () => {
    const events = explainEvents(request([record], () => 'Прирост 12345678 рублей.'));
    const warning = events.find((event) => event.type === 'warning');
    expect(warning).toMatchObject({ code: 'number-dropped' });
    const caption = events.find((event) => event.type === 'caption');
    expect(caption).toBeDefined();
    if (caption?.type === 'caption') {
      expect(caption.text).not.toContain('12345678');
      expect(caption.guarded).toBe(true);
    }
  });

  it('refuses with no-trace-entry instead of inventing an explanation', () => {
    const events = explainEvents(request([], () => 'never used'));
    const cards = cardsOf(events);
    expect(cards).toHaveLength(1);
    expect(cards[0].type).toBe('error');
    expect((cards[0].payload as { code: string }).code).toBe(NO_TRACE_ENTRY);
    expect(cards[0].provenance).toBe('none');
  });

  it('emits no rule card and no invented number when the journal is empty', () => {
    const events = explainEvents(request([], () => 'never used'));
    expect(cardsOf(events).some((card) => card.type === 'rule')).toBe(false);
    const caption = events.find((event) => event.type === 'caption');
    if (caption?.type === 'caption') {
      expect(unsupportedNumbers(caption.text, [])).toEqual([]);
    }
  });
});
