import { describe, expect, it } from 'vitest';
import en from './en.json';
import ru from './ru.json';

describe('i18n dictionaries', () => {
  it('has identical key sets in ru and en', () => {
    expect(Object.keys(ru).sort()).toEqual(Object.keys(en).sort());
  });

  it('has non-empty string values', () => {
    for (const dictionary of [ru, en]) {
      for (const [key, value] of Object.entries(dictionary)) {
        expect(typeof value, key).toBe('string');
        expect(value.length, key).toBeGreaterThan(0);
      }
    }
  });
});
