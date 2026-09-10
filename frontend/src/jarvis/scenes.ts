import type {
  JarvisAskContext,
  JarvisCard,
  JarvisEvent,
  JarvisStatusState
} from './transport/events';

export interface SceneCard {
  id: string;
  order: number;
  card: JarvisCard;
  tool: string | null;
  args: Record<string, unknown> | null;
}

export interface Scene {
  id: string;
  sourceId: string;
  question: string;
  context: JarvisAskContext;
  cards: SceneCard[];
  captionDraft: string;
  caption: string | null;
  answerDraft: string;
  answer: string | null;
  ts: string | null;
  guarded: boolean;
  warnings: { code: string; detail: string }[];
  error: { code: string; message: string } | null;
  done: boolean;
}

export interface ScenesState {
  scenes: Scene[];
  activeIndex: number;
  suggestions: string[];
  status: JarvisStatusState | null;
  tool: string | null;
  seq: number;
}

export const MAX_ORBIT_CARDS = 8;

export const emptyScenes: ScenesState = {
  scenes: [],
  activeIndex: -1,
  suggestions: [],
  status: null,
  tool: null,
  seq: 0
};

export const activeScene = (state: ScenesState): Scene | null =>
  state.activeIndex < 0 ? null : (state.scenes[state.activeIndex] ?? null);

const replaceScene = (
  state: ScenesState,
  sourceId: string,
  patch: (scene: Scene) => Scene
): ScenesState => {
  let index = -1;
  for (let i = state.scenes.length - 1; i >= 0; i -= 1) {
    if (state.scenes[i].sourceId === sourceId || state.scenes[i].id === sourceId) {
      index = i;
      break;
    }
  }
  if (index < 0) {
    return state;
  }
  const scenes = state.scenes.slice();
  scenes[index] = patch(scenes[index]);
  return { ...state, scenes };
};

export const scenesReducer = (state: ScenesState, event: JarvisEvent): ScenesState => {
  if (event.type === 'scene') {
    const seq = state.seq + 1;
    const scene: Scene = {
      id: `${event.scene_id}#${seq}`,
      sourceId: event.scene_id,
      question: event.question,
      context: event.context,
      cards: [],
      captionDraft: '',
      caption: null,
      answerDraft: '',
      answer: null,
      ts: event.ts ?? null,
      guarded: false,
      warnings: [],
      error: null,
      done: false
    };
    const scenes = [...state.scenes, scene];
    return {
      ...state,
      scenes,
      seq,
      activeIndex: scenes.length - 1,
      status: 'thinking',
      tool: null
    };
  }
  if (event.type === 'status') {
    return { ...state, status: event.state, tool: event.tool ?? null };
  }
  if (event.type === 'card') {
    return replaceScene(state, event.scene_id, (scene) => {
      if (scene.cards.some((entry) => entry.id === event.card_id)) {
        return scene;
      }
      const entry: SceneCard = {
        id: event.card_id,
        order: event.order,
        card: event.card,
        tool: event.tool ?? null,
        args: event.args ?? null
      };
      const cards = [...scene.cards, entry]
        .sort((a, b) => a.order - b.order)
        .slice(0, MAX_ORBIT_CARDS);
      return { ...scene, cards };
    });
  }
  if (event.type === 'caption_delta') {
    return replaceScene(state, event.scene_id, (scene) => ({
      ...scene,
      captionDraft: scene.captionDraft + event.text
    }));
  }
  if (event.type === 'caption') {
    return replaceScene(state, event.scene_id, (scene) => ({
      ...scene,
      caption: event.text,
      captionDraft: event.text,
      guarded: event.guarded
    }));
  }
  if (event.type === 'answer_delta') {
    return replaceScene(state, event.scene_id, (scene) => ({
      ...scene,
      answerDraft: scene.answerDraft + event.text
    }));
  }
  if (event.type === 'answer') {
    return replaceScene(state, event.scene_id, (scene) => ({
      ...scene,
      answer: event.text,
      answerDraft: event.text
    }));
  }
  if (event.type === 'capabilities') {
    return state;
  }
  if (event.type === 'warning') {
    const target = activeScene(state);
    if (target === null) {
      return state;
    }
    return replaceScene(state, target.id, (scene) => ({
      ...scene,
      warnings: [...scene.warnings, { code: event.code, detail: event.detail }]
    }));
  }
  if (event.type === 'suggestions') {
    return { ...state, suggestions: event.items.map((item) => item.text) };
  }
  if (event.type === 'done') {
    return replaceScene({ ...state, status: null, tool: null }, event.scene_id, (scene) => ({
      ...scene,
      done: true
    }));
  }
  if (event.type === 'error') {
    const target = activeScene(state);
    if (target === null) {
      return { ...state, status: null, tool: null };
    }
    return replaceScene({ ...state, status: null, tool: null }, target.id, (scene) => ({
      ...scene,
      error: { code: event.code, message: event.message },
      done: true
    }));
  }
  return state;
};

export const adoptScene = (
  state: ScenesState,
  pendingId: string,
  event: Extract<JarvisEvent, { type: 'scene' }>
): ScenesState => {
  const index = state.scenes.findIndex((scene) => scene.sourceId === pendingId);
  if (index < 0) {
    return scenesReducer(state, event);
  }
  const scenes = state.scenes.slice();
  scenes[index] = {
    ...scenes[index],
    sourceId: event.scene_id,
    question: event.question,
    context: event.context,
    ts: event.ts ?? scenes[index].ts
  };
  return { ...state, scenes, activeIndex: index, status: 'thinking', tool: null };
};

export const selectSceneAt = (state: ScenesState, index: number): ScenesState => {
  if (state.scenes.length === 0) {
    return state;
  }
  const clamped = Math.min(Math.max(index, 0), state.scenes.length - 1);
  return clamped === state.activeIndex ? state : { ...state, activeIndex: clamped };
};
