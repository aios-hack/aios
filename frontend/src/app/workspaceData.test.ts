import { describe, expect, it } from 'vitest';
import { DATASETS } from '../data/datasets';
import { WORKSPACES } from '../state/ConsoleContext';
import { datasetsFor, WORKSPACE_DATASETS } from './workspaceData';

describe('workspace data declaration', () => {
  it('declares a dataset list for every workspace', () => {
    for (const workspace of WORKSPACES) {
      expect(datasetsFor(workspace).length).toBeGreaterThan(0);
    }
  });

  it('names only datasets that exist in the registry', () => {
    const known = new Set(Object.keys(DATASETS));
    for (const workspace of WORKSPACES) {
      for (const name of datasetsFor(workspace)) {
        expect(known.has(name)).toBe(true);
      }
    }
  });

  it('covers every workspace exactly once', () => {
    expect(Object.keys(WORKSPACE_DATASETS).sort()).toEqual([...WORKSPACES].sort());
  });
});
