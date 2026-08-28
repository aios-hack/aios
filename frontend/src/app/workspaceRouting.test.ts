import { describe, expect, it } from 'vitest';
import { formatRoute, parseRoute } from './useWorkspaceRouting';

describe('workspace routing', () => {
  it('reads a workspace and its view from the path', () => {
    expect(parseRoute('/history/wall')).toEqual({
      workspace: 'history',
      view: 'wall'
    });
  });

  it('falls back to the first view when the path names none', () => {
    expect(parseRoute('/money')).toEqual({ workspace: 'money', view: 'rank' });
  });

  it('ignores a path that names no known workspace', () => {
    expect(parseRoute('/nowhere/wall')).toBeNull();
    expect(parseRoute('/')).toBeNull();
    expect(parseRoute('')).toBeNull();
  });

  it('reads a trailing slash the same as the bare path', () => {
    expect(parseRoute('/history/wall/')).toEqual(parseRoute('/history/wall'));
  });

  it('still understands the hash form old links were shared with', () => {
    expect(parseRoute('#/history/wall')).toEqual(parseRoute('/history/wall'));
  });

  it('formats a clean path, with no hash left in it', () => {
    expect(formatRoute({ workspace: 'decisions', view: 'rules' })).toBe('/decisions/rules');
  });

  it('round-trips every route it formats', () => {
    const route = { workspace: 'decisions', view: 'rules' } as const;
    expect(parseRoute(formatRoute(route))).toEqual(route);
  });
});
