import { describe, expect, it } from 'vitest';
import { activeScene, emptyScenes, selectSceneAt } from '@/jarvis/model/scenes';
import type { JarvisEvent } from '@/jarvis/transport/events';
import { context, opened, play } from '@support/scenesFixtures';

describe('the stack of previous scenes', () => {
  it('keeps earlier scenes and moves the newest to the front', () => {
    const state = play(
      [{ type: 'scene', scene_id: 's-02', question: 'кто', context }],
      opened()
    );
    expect(state.scenes.length).toBe(2);
    expect(state.activeIndex).toBe(1);
    expect(state.scenes[0].question).toBe('почему');
  });

  it('keeps every scene, so the memory rail never loses one', () => {
    const events: JarvisEvent[] = Array.from({ length: 16 }, (_, index) => ({
      type: 'scene',
      scene_id: `s-${index}`,
      question: `вопрос ${index}`,
      context
    }));
    const state = play(events);
    expect(state.scenes.length).toBe(16);
    expect(state.scenes[state.scenes.length - 1].question).toBe('вопрос 15');
  });

  it('clamps a selection to the ends of the stack', () => {
    const state = play([{ type: 'scene', scene_id: 's-02', question: 'кто', context }], opened());
    expect(selectSceneAt(state, -5).activeIndex).toBe(0);
    expect(selectSceneAt(state, 99).activeIndex).toBe(1);
  });

  it('returns the same object when the selection does not move', () => {
    const state = opened();
    expect(selectSceneAt(state, 0)).toBe(state);
    expect(selectSceneAt(emptyScenes, 3)).toBe(emptyScenes);
  });

  it('reports no active scene before anything is asked', () => {
    expect(activeScene(emptyScenes)).toBeNull();
  });
});

describe('two answers that reuse one scene_id stay two separate scenes', () => {
  const sceneEvent = (question: string): JarvisEvent => ({
    type: 'scene',
    scene_id: 's-01',
    question,
    context
  });

  const cardEvent = (cardId: string): JarvisEvent => ({
    type: 'card',
    scene_id: 's-01',
    card_id: cardId,
    order: 1,
    card: { type: 'metric', title: cardId, payload: {}, provenance: 'demo' }
  });

  it('gives every scene its own key even when the transport repeats scene_id', () => {
    const state = play([sceneEvent('первый'), sceneEvent('второй')]);
    expect(state.scenes).toHaveLength(2);
    expect(new Set(state.scenes.map((scene) => scene.id)).size).toBe(2);
  });

  it('files a card on the newest scene, not the first one that answered', () => {
    const state = play([
      sceneEvent('первый'),
      cardEvent('c-old'),
      sceneEvent('второй'),
      cardEvent('c-new')
    ]);
    expect(state.scenes[0].cards.map((entry) => entry.id)).toEqual(['c-old']);
    expect(state.scenes[1].cards.map((entry) => entry.id)).toEqual(['c-new']);
  });

  it('puts the caption on the newest scene too', () => {
    const state = play([
      sceneEvent('первый'),
      sceneEvent('второй'),
      { type: 'caption', scene_id: 's-01', text: 'ответ на второй', guarded: true }
    ]);
    expect(state.scenes[0].caption).toBeNull();
    expect(state.scenes[1].caption).toBe('ответ на второй');
  });
});
