import type { Workspace, WorkspaceView } from '../../state/ConsoleContext';
import type { ConsoleAction } from '../actions/consoleAction';

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
  'guide',
  'doc',
  'system-map',
  'status-board',
  'run-list',
  'run',
  'constraints',
  'council',
  'physics'
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

export interface JarvisCapabilitiesEvent {
  type: 'capabilities';
  tts: boolean;
  stt: 'server' | 'browser' | 'none';
  docs: number;
  sessions: number;
}

export type JarvisEvent =
  | {
      type: 'scene';
      scene_id: string;
      question: string;
      context: JarvisAskContext;
      ts?: string;
      session_id?: string;
    }
  | { type: 'status'; state: JarvisStatusState; tool?: string }
  | {
      type: 'card';
      scene_id: string;
      card_id: string;
      order: number;
      card: JarvisCard;
      tool?: string;
      args?: Record<string, unknown>;
    }
  | { type: 'caption_delta'; scene_id: string; text: string }
  | { type: 'caption'; scene_id: string; text: string; guarded: boolean }
  | { type: 'answer_delta'; scene_id: string; text: string }
  | { type: 'answer'; scene_id: string; text: string; guarded: boolean }
  | JarvisCapabilitiesEvent
  | { type: 'warning'; code: string; detail: string }
  | { type: 'suggestions'; items: { text: string }[] }
  | { type: 'done'; scene_id: string; tool_rounds: number; elapsed_ms: number }
  | { type: 'error'; code: string; message: string };
