import { describe, expect, it } from 'vitest';
import { formatRoute, parseRoute } from './useWorkspaceRouting';

describe('workspace routing', () => {
  it('reads a workspace and its view from the hash', () => {
    expect(parseRoute('#/history/wall')).toEqual({
      workspace: 'history',
      view: 'wall'
    });
  });

  it('falls back to the first view when the hash names none', () => {
    expect(parseRoute('#/money')).toEqual({ workspace: 'money', view: 'rank' });
  });

  it('ignores a hash that names no known workspace', () => {
    expect(parseRoute('#/nowhere/wall')).toBeNull();
    expect(parseRoute('')).toBeNull();
  });

  it('round-trips every route it formats', () => {
    const route = { workspace: 'decisions', view: 'rules' } as const;
    expect(parseRoute(formatRoute(route))).toEqual(route);
  });
});
