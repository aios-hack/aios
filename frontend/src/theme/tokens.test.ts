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

const themeFile = (name: string): string =>
  readFileSync(join(srcDir, 'theme', name), 'utf-8');

const themeCss = ['tokens.light.css', 'tokens.dark.css', 'fonts.css']
  .map(themeFile)
  .join('\n');

describe('design tokens', () => {
  it('keeps the map ceiling token in the theme layer', () => {
    expect(themeCss).toContain('--size-map-max');
  });

  it('keeps hex colors only in the theme layer', () => {
    const offenders: string[] = [];
    for (const file of collectFiles(srcDir)) {
      if (file.includes(join('src', 'theme'))) {
        continue;
      }
      if (hexColor.test(readFileSync(file, 'utf-8'))) {
        offenders.push(file);
      }
    }
    expect(offenders).toEqual([]);
  });

  it('defines dark theme overrides for every color token', () => {
    const lightBlock = themeFile('tokens.light.css');
    const darkBlock = themeFile('tokens.dark.css');
    const colorTokens = [...lightBlock.matchAll(/--color-[\w-]+/g)].map((match) => match[0]);
    expect(colorTokens.length).toBeGreaterThan(0);
    for (const token of new Set(colorTokens)) {
      expect(darkBlock, token).toContain(token);
    }
  });
});

describe('industrial console tokens', () => {
  const css = themeCss;

  it('serves a monospace family locally for numeric values', () => {
    expect(css).toContain("font-family: 'JetBrains Mono'");
    expect(css).toContain('/fonts/jetbrains-mono-cyrillic.woff2');
    expect(css).toContain('/fonts/jetbrains-mono-latin.woff2');
    expect(css).toMatch(/--font-family-mono:\s*'JetBrains Mono'/);
  });

  it('names a colour token for every physical quantity', () => {
    for (const token of [
      '--color-oil',
      '--color-water',
      '--color-injection',
      '--scale-watercut-0',
      '--scale-watercut-1'
    ]) {
      expect(css, token).toContain(token);
    }
  });

  it('drops the landing vocabulary: dot grid, and keeps shadows to the transport alone', () => {
    expect(css).not.toContain('--dot-grid');
    const shadows = [...css.matchAll(/--shadow-([\w-]+):/g)].map((m) => m[1]);
    expect(new Set(shadows)).toEqual(new Set(['transport', 'backdrop', 'accent', 'accent-hover']));
  });

  it('keeps every corner radius at eight pixels or less (pills excepted)', () => {
    const radii = [...css.matchAll(/--radius-(?!pill)[\w-]*:\s*(\d+)px/g)].map((m) => Number(m[1]));
    expect(radii.length).toBeGreaterThan(0);
    for (const radius of radii) {
      expect(radius).toBeLessThanOrEqual(8);
    }
    expect(css).toContain('--radius-pill: 999px');
  });

  it('sets a table row height in the dense range', () => {
    const row = css.match(/--size-row:\s*(\d+)px/);
    expect(row).not.toBeNull();
    const height = Number(row?.[1]);
    expect(height).toBeGreaterThanOrEqual(24);
    expect(height).toBeLessThanOrEqual(28);
  });
});

describe('base stylesheet', () => {
  const base = readFileSync(join(srcDir, 'styles.css'), 'utf-8');

  it('puts tabular numerals in the base layer, not in single views', () => {
    expect(base).toMatch(/body\s*\{[^}]*font-variant-numeric:\s*tabular-nums/);
  });

  it('lets the tool use the full width of the screen', () => {
    expect(base).not.toContain('--size-content-max');
    expect(base).not.toContain('body::before');
  });
});

describe('view stylesheets', () => {
  it('carry no shadows or hover lifts (the play button is the one sanctioned pill, V11)', () => {
    const offenders: string[] = [];
    for (const file of collectFiles(srcDir)) {
      if (!file.endsWith('.css') || file.endsWith(join('theme', 'tokens.css'))) {
        continue;
      }
      if (
        file.endsWith(join('Timeline', 'StepControls.css')) ||
        file.endsWith(join('PlaybackSettings', 'PlaybackSettings.css')) ||
        file.endsWith(join('app', 'TimeScale.css')) ||
        file.endsWith(join('HeaderControls', 'HeaderControls.css'))
      ) {
        continue;
      }
      const text = readFileSync(file, 'utf-8');
      if (/var\(--shadow|translateY\(-\d+px\)/.test(text)) {
        offenders.push(file);
      }
    }
    expect(offenders).toEqual([]);
  });

  it('never caps the scene with the card-context map ceiling (R10)', () => {
    const offenders: string[] = [];
    for (const file of collectFiles(srcDir)) {
      if (!file.endsWith('.css') || file.includes(join('views', 'FieldMap'))) {
        continue;
      }
      const text = readFileSync(file, 'utf-8');
      if (file.includes(join('src', 'theme'))) {
        continue;
      }
      if (text.includes('--size-map-max')) {
        offenders.push(file);
      }
    }
    expect(offenders).toEqual([]);
  });
});

describe('scroll padding for obscured focus (R16)', () => {
  const consoleCss = readFileSync(join(srcDir, 'app', 'console.css'), 'utf-8');
  const paletteCss = readFileSync(
    join(srcDir, 'ui', 'CommandPalette', 'CommandPalette.css'),
    'utf-8'
  );

  it('keeps the scene scroller clear of the strip and the time axis with token values', () => {
    const match = consoleCss.match(/\.console-main\s*\{[^}]*\}/);
    expect(match).not.toBeNull();
    const block = match?.[0] ?? '';
    expect(block).toMatch(/scroll-padding-block:\s*var\(--h-strip\)\s+var\(--h-timeaxis\)/);
  });

  it('keeps the command palette list clear of the strip and the time axis with token values', () => {
    const match = paletteCss.match(/\.palette-list\s*\{[^}]*\}/);
    expect(match).not.toBeNull();
    const block = match?.[0] ?? '';
    expect(block).toMatch(/scroll-padding-block:\s*var\(--h-strip\)\s+var\(--h-timeaxis\)/);
  });

  it('never expresses scroll-padding as a bare literal', () => {
    for (const css of [consoleCss, paletteCss]) {
      const declarations = [...css.matchAll(/scroll-padding[\w-]*:\s*([^;]+);/g)];
      expect(declarations.length).toBeGreaterThan(0);
      for (const [, value] of declarations) {
        expect(value).not.toMatch(/\d+px/);
        expect(value).toContain('var(--h-');
      }
    }
  });
});
