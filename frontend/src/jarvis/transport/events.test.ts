import { describe, expect, it } from 'vitest';
import { CARD_TYPES, parseCard, parseConsoleAction, parseEvent, parseEventLine } from './events';

const context = {
  scenario: 'base',
  step: 96,
  date: '2015-01-01',
  selected_well: '51',
  workspace: 'field',
  view: 'projection'
};

describe('event validators accept every documented event', () => {
  it('reads a scene with its console context', () => {
    const event = parseEvent({ type: 'scene', scene_id: 's-01', question: 'почему', context });
    expect(event?.type).toBe('scene');
    expect(event?.type === 'scene' && event.context.step).toBe(96);
  });

  it('reads all three status states and keeps the tool name', () => {
    for (const state of ['thinking', 'tool', 'composing']) {
      expect(parseEvent({ type: 'status', state })?.type).toBe('status');
    }
    const withTool = parseEvent({ type: 'status', state: 'tool', tool: 'well_snapshot' });
    expect(withTool?.type === 'status' && withTool.tool).toBe('well_snapshot');
  });

  it('reads a card of every type in the catalogue', () => {
    for (const type of CARD_TYPES) {
      const card = parseCard({ type, title: 'T', payload: {}, provenance: 'model-z-base-run' });
      expect(card?.type, type).toBe(type);
    }
  });

  it('reads caption deltas and the guarded final caption', () => {
    expect(parseEvent({ type: 'caption_delta', scene_id: 's', text: 'Скв' })?.type).toBe(
      'caption_delta'
    );
    const caption = parseEvent({ type: 'caption', scene_id: 's', text: 'готово', guarded: true });
    expect(caption?.type === 'caption' && caption.guarded).toBe(true);
  });

  it('treats a caption without the guarded flag as not guarded', () => {
    const caption = parseEvent({ type: 'caption', scene_id: 's', text: 'готово' });
    expect(caption?.type === 'caption' && caption.guarded).toBe(false);
  });

  it('reads warnings, suggestions, done and error', () => {
    expect(parseEvent({ type: 'warning', code: 'number-dropped', detail: 'x' })?.type).toBe(
      'warning'
    );
    const suggestions = parseEvent({ type: 'suggestions', items: [{ text: 'a' }, { text: 'b' }] });
    expect(suggestions?.type === 'suggestions' && suggestions.items.length).toBe(2);
    expect(parseEvent({ type: 'done', scene_id: 's', tool_rounds: 2, elapsed_ms: 10 })?.type).toBe(
      'done'
    );
    expect(parseEvent({ type: 'error', code: 'timeout', message: 'долго' })?.type).toBe('error');
  });
});

describe('event validators reject rubbish instead of trusting it', () => {
  it('refuses an unknown event type', () => {
    expect(parseEvent({ type: 'nonsense' })).toBeNull();
  });

  it('refuses a scene whose workspace is not a console workspace', () => {
    expect(
      parseEvent({
        type: 'scene',
        scene_id: 's',
        question: 'q',
        context: { ...context, workspace: 'kitchen' }
      })
    ).toBeNull();
  });

  it('refuses a scene whose view does not belong to its workspace', () => {
    expect(
      parseEvent({
        type: 'scene',
        scene_id: 's',
        question: 'q',
        context: { ...context, view: 'rank' }
      })
    ).toBeNull();
  });

  it('refuses a card of an unknown type and a card without provenance', () => {
    expect(parseCard({ type: 'stonks', title: 'T', payload: {}, provenance: 'p' })).toBeNull();
    expect(parseCard({ type: 'metric', title: 'T', payload: {} })).toBeNull();
  });

  it('refuses a status with a state outside the contract', () => {
    expect(parseEvent({ type: 'status', state: 'napping' })).toBeNull();
  });

  it('refuses non-objects, arrays and empty input', () => {
    expect(parseEvent(null)).toBeNull();
    expect(parseEvent([])).toBeNull();
    expect(parseEvent('scene')).toBeNull();
    expect(parseEventLine('')).toBeNull();
    expect(parseEventLine('{ not json')).toBeNull();
  });

  it('drops suggestion entries that are not text', () => {
    const parsed = parseEvent({ type: 'suggestions', items: [{ text: 'a' }, { nope: 1 }, 5] });
    expect(parsed?.type === 'suggestions' && parsed.items).toEqual([{ text: 'a' }]);
  });
});

describe('console actions are filtered against the real route table', () => {
  it('keeps a workspace and view that exist together', () => {
    const action = parseConsoleAction({ workspace: 'money', view: 'rank', step: 12.7 });
    expect(action?.workspace).toBe('money');
    expect(action?.view).toBe('rank');
    expect(action?.step).toBe(12);
  });

  it('drops a view that does not belong to the workspace but keeps the workspace', () => {
    const action = parseConsoleAction({ workspace: 'money', view: 'projection' });
    expect(action?.workspace).toBe('money');
    expect(action?.view).toBeUndefined();
  });

  it('drops the workspace entirely when it is unknown', () => {
    const action = parseConsoleAction({ workspace: 'cellar', view: 'rank', well: '51' });
    expect(action?.workspace).toBeUndefined();
    expect(action?.well).toBe('51');
  });

  it('keeps an explicit null well as a deselect', () => {
    expect(parseConsoleAction({ well: null })?.well).toBeNull();
  });

  it('returns null for a non-object action', () => {
    expect(parseConsoleAction('money')).toBeNull();
  });

  it('leaves a card without an action free of an empty action object', () => {
    const card = parseCard({
      type: 'metric',
      title: 'T',
      payload: {},
      provenance: 'p',
      action: {}
    });
    expect(card?.action).toBeUndefined();
  });
});
