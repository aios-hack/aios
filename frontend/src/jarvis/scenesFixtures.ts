import {
  emptyScenes,
  scenesReducer,
  type ScenesState
} from './scenes';
import type { JarvisCard, JarvisEvent } from './transport/events';

export const context = {
  scenario: 'base',
  step: 72,
  date: '2013-01-01',
  selected_well: '51',
  workspace: 'field' as const,
  view: 'projection' as const
};

export const card = (title: string): JarvisCard => ({
  type: 'metric',
  title,
  payload: { value: 1 },
  provenance: 'model-z-base-run'
});

export const play = (events: JarvisEvent[], from: ScenesState = emptyScenes): ScenesState =>
  events.reduce(scenesReducer, from);

export const opened = (id = 's-01'): ScenesState =>
  play([{ type: 'scene', scene_id: id, question: 'почему', context }]);
