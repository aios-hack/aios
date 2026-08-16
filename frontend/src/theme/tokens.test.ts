import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const srcDir = join(process.cwd(), 'src');
const hexColor = /#[0-9a-fA-F]{3,8}\b/;

const collectFiles = (dir: string): string[] => {
  const found: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      found.push(...collectFiles(full));
    } else if (/\.(ts|tsx|css|json)$/.test(entry.name)) {
      found.push(full);
    }
  }
  return found;
};

describe('design tokens', () => {
  it('keeps hex colors only in tokens.css', () => {
    const offenders: string[] = [];
    for (const file of collectFiles(srcDir)) {
      if (file.endsWith(join('theme', 'tokens.css'))) {
        continue;
      }
      if (hexColor.test(readFileSync(file, 'utf-8'))) {
        offenders.push(file);
      }
    }
    expect(offenders).toEqual([]);
  });

  it('defines dark theme overrides for every color token', () => {
    const css = readFileSync(join(srcDir, 'theme', 'tokens.css'), 'utf-8');
    const [lightBlock, darkBlock] = css.split("[data-theme='dark']");
    const colorTokens = [...lightBlock.matchAll(/--color-[\w-]+/g)].map((match) => match[0]);
    expect(colorTokens.length).toBeGreaterThan(0);
    for (const token of new Set(colorTokens)) {
      expect(darkBlock, token).toContain(token);
    }
  });
});
