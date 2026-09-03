import type { Workspace, WorkspaceView } from '../../state/ConsoleContext';
import { isView, isWorkspace, type ConsoleAction } from '../actions/consoleAction';

export const CARD_TYPES = [
  'metric',
  'well',
  'well-list',
  'field-map',
  'series',
  'rule',
  'compare',
  'event-strip',
  'pattern',
  'error',
  'glossary',
  'guide'
] as const;

export type CardType = (typeof CARD_TYPES)[number];

export interface JarvisCard {
  type: CardType;
  title: string;
  payload: unknown;
  provenance: string;
  action?: ConsoleAction;
}

export type { ConsoleAction };

export interface JarvisAskContext {
  scenario: string;
  step: number;
  date: string;
  selected_well: string | null;
  workspace: Workspace;
  view: WorkspaceView;
}

export type JarvisStatusState = 'thinking' | 'tool' | 'composing';

export type JarvisEvent =
  | { type: 'scene'; scene_id: string; question: string; context: JarvisAskContext }
  | { type: 'status'; state: JarvisStatusState; tool?: string }
  | { type: 'card'; scene_id: string; card_id: string; order: number; card: JarvisCard }
  | { type: 'caption_delta'; scene_id: string; text: string }
  | { type: 'caption'; scene_id: string; text: string; guarded: boolean }
  | { type: 'warning'; code: string; detail: string }
  | { type: 'suggestions'; items: { text: string }[] }
  | { type: 'done'; scene_id: string; tool_rounds: number; elapsed_ms: number }
  | { type: 'error'; code: string; message: string };

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

const str = (value: unknown): value is string => typeof value === 'string';
const num = (value: unknown): value is number =>
  typeof value === 'number' && Number.isFinite(value);

export const parseConsoleAction = (value: unknown): ConsoleAction | null => {
  if (!isRecord(value)) {
    return null;
  }
  const action: ConsoleAction = {};
  if (isWorkspace(value.workspace)) {
    action.workspace = value.workspace;
    if (isView(value.view, value.workspace)) {
      action.view = value.view;
    }
  }
  if (str(value.scenario)) {
    action.scenario = value.scenario;
  }
  if (num(value.step)) {
    action.step = Math.trunc(value.step);
  }
  if (str(value.well) || value.well === null) {
    action.well = value.well;
  }
  if (typeof value.play === 'boolean') {
    action.play = value.play;
  }
  if (str(value.spotlight)) {
    action.spotlight = value.spotlight;
  }
  return action;
};

export const parseCard = (value: unknown): JarvisCard | null => {
  if (!isRecord(value)) {
    return null;
  }
  if (!str(value.type) || !(CARD_TYPES as readonly string[]).includes(value.type)) {
    return null;
  }
  if (!str(value.title) || !str(value.provenance) || value.payload === undefined) {
    return null;
  }
  const action = parseConsoleAction(value.action);
  return {
    type: value.type as CardType,
    title: value.title,
    payload: value.payload,
    provenance: value.provenance,
    ...(action === null || Object.keys(action).length === 0 ? {} : { action })
  };
};

const parseContext = (value: unknown): JarvisAskContext | null => {
  if (!isRecord(value) || !isWorkspace(value.workspace)) {
    return null;
  }
  if (!isView(value.view, value.workspace) || !str(value.scenario)) {
    return null;
  }
  if (!num(value.step) || !str(value.date)) {
    return null;
  }
  return {
    scenario: value.scenario,
    step: Math.trunc(value.step),
    date: value.date,
    selected_well: str(value.selected_well) ? value.selected_well : null,
    workspace: value.workspace,
    view: value.view
  };
};

export const parseEvent = (value: unknown): JarvisEvent | null => {
  if (!isRecord(value) || !str(value.type)) {
    return null;
  }
  if (value.type === 'scene') {
    const context = parseContext(value.context);
    if (!str(value.scene_id) || !str(value.question) || context === null) {
      return null;
    }
    return { type: 'scene', scene_id: value.scene_id, question: value.question, context };
  }
  if (value.type === 'status') {
    if (value.state !== 'thinking' && value.state !== 'tool' && value.state !== 'composing') {
      return null;
    }
    return {
      type: 'status',
      state: value.state,
      ...(str(value.tool) ? { tool: value.tool } : {})
    };
  }
  if (value.type === 'card') {
    const card = parseCard(value.card);
    if (!str(value.scene_id) || !str(value.card_id) || !num(value.order) || card === null) {
      return null;
    }
    return {
      type: 'card',
      scene_id: value.scene_id,
      card_id: value.card_id,
      order: Math.trunc(value.order),
      card
    };
  }
  if (value.type === 'caption_delta') {
    if (!str(value.scene_id) || !str(value.text)) {
      return null;
    }
    return { type: 'caption_delta', scene_id: value.scene_id, text: value.text };
  }
  if (value.type === 'caption') {
    if (!str(value.scene_id) || !str(value.text)) {
      return null;
    }
    return {
      type: 'caption',
      scene_id: value.scene_id,
      text: value.text,
      guarded: value.guarded === true
    };
  }
  if (value.type === 'warning') {
    if (!str(value.code)) {
      return null;
    }
    return { type: 'warning', code: value.code, detail: str(value.detail) ? value.detail : '' };
  }
  if (value.type === 'suggestions') {
    if (!Array.isArray(value.items)) {
      return null;
    }
    const items = value.items
      .filter((item): item is Record<string, unknown> => isRecord(item) && str(item.text))
      .map((item) => ({ text: item.text as string }));
    return { type: 'suggestions', items };
  }
  if (value.type === 'done') {
    if (!str(value.scene_id)) {
      return null;
    }
    return {
      type: 'done',
      scene_id: value.scene_id,
      tool_rounds: num(value.tool_rounds) ? Math.trunc(value.tool_rounds) : 0,
      elapsed_ms: num(value.elapsed_ms) ? value.elapsed_ms : 0
    };
  }
  if (value.type === 'error') {
    if (!str(value.code)) {
      return null;
    }
    return { type: 'error', code: value.code, message: str(value.message) ? value.message : '' };
  }
  return null;
};

export const parseEventLine = (line: string): JarvisEvent | null => {
  const text = line.trim();
  if (text.length === 0) {
    return null;
  }
  try {
    return parseEvent(JSON.parse(text));
  } catch {
    return null;
  }
};
