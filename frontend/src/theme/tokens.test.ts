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
        file.endsWith(join('HeaderControls', 'HeaderControls.css')) ||
        file.endsWith(join('TrustBoard', 'StatusChip.css')) ||
        file.endsWith(join('shared', 'iconButton.css'))
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
  const consoleCss = ['console.css', 'consoleHeader.css', 'consoleScene.css']
    .map((name) => readFileSync(join(srcDir, 'app', name), 'utf-8'))
    .join('\n');
  const paletteCss = readFileSync(
    join(srcDir, 'ui', 'CommandPalette', 'CommandPalette.css'),
    'utf-8'
  );

  it('keeps the scene scroller clear of the strip and the time axis with token values', () => {
    const match = consoleCss.match(/\.console-main\s*\{[^}]*\}/);
    expect(match).not.toBeNull();
    const block = match?.[0] ?? '';
    expect(block).toMatch(/scroll-padding-block:\s*var\(--h-header\)\s+var\(--h-timeaxis\)/);
  });

  it('keeps the command palette list clear of the strip and the time axis with token values', () => {
    const match = paletteCss.match(/\.palette-list\s*\{[^}]*\}/);
    expect(match).not.toBeNull();
    const block = match?.[0] ?? '';
    expect(block).toMatch(/scroll-padding-block:\s*var\(--h-header\)\s+var\(--h-timeaxis\)/);
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

const channel = (value: number): number => {
  const v = value / 255;
  return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
};

const luminance = ([r, g, b]: number[]): number =>
  0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);

const contrast = (a: number[], b: number[]): number => {
  const [l1, l2] = [luminance(a), luminance(b)];
  return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
};

const flatten = (fg: number[], bg: number[], alpha: number): number[] =>
  fg.map((c, i) => c * alpha + bg[i] * (1 - alpha));

const hexToRgb = (hex: string): number[] => {
  const clean = hex.replace('#', '');
  return [0, 2, 4].map((i) => parseInt(clean.slice(i, i + 2), 16));
};

const readToken = (css: string, name: string): string => {
  const match = css.match(new RegExp(`${name}:\s*([^;]+);`));
  if (!match) {
    throw new Error(`token ${name} not found`);
  }
  return match[1].trim();
};

const resolve = (css: string, name: string, bg: number[]): number[] => {
  const raw = readToken(css, name);
  if (raw.startsWith('#')) {
    return hexToRgb(raw);
  }
  const parts = raw.match(/[\d.]+/g);
  if (!parts) {
    throw new Error(`token ${name} is not a colour`);
  }
  const [r, g, b, a] = parts.map(Number);
  return flatten([r, g, b], bg, a ?? 1);
};

describe('readable text on every surface', () => {
  const themes = [
    { name: 'light', css: themeFile('tokens.light.css') },
    { name: 'dark', css: themeFile('tokens.dark.css') }
  ];
  const surfaces = ['--color-bg', '--color-surface', '--color-surface-sunken'];
  const texts = ['--color-text', '--color-text-muted', '--color-text-subtle', '--color-text-faint'];

  for (const theme of themes) {
    for (const surface of surfaces) {
      const bg = resolve(theme.css, surface, [255, 255, 255]);
      for (const text of texts) {
        it(`${theme.name}: ${text} clears 4.5:1 on ${surface}`, () => {
          expect(contrast(resolve(theme.css, text, bg), bg)).toBeGreaterThanOrEqual(4.5);
        });
      }

      it(`${theme.name}: --color-accent stays distinguishable on ${surface}`, () => {
        expect(contrast(resolve(theme.css, '--color-accent', bg), bg)).toBeGreaterThanOrEqual(3);
      });
    }
  }
});

describe('components ship the styles they render', () => {
  const routeComponents = [
    { file: join(srcDir, 'views', 'Scenarios', 'ScenarioLibrary.tsx'), css: 'ScenariosLibrary.css' },
    { file: join(srcDir, 'views', 'Scenarios', 'Scenarios.tsx'), css: 'ScenariosLibrary.css' },
    { file: join(srcDir, 'views', 'Scenarios', 'ScenarioComparison.tsx'), css: 'ScenariosCompare.css' },
    { file: join(srcDir, 'views', 'Scenarios', 'ConstraintsEditor.tsx'), css: 'ScenariosEditor.css' }
  ];

  for (const { file, css } of routeComponents) {
    it(`${file.split(/[\/]/).pop()} imports ${css}`, () => {
      expect(readFileSync(file, 'utf-8')).toContain(`import './${css}'`);
    });
  }
});

describe('scrollbars are themed, never native chrome', () => {
  const scrollCss = themeFile('scrollbars.css');

  it('is imported by the token entry point so every scroller inherits it', () => {
    expect(themeFile('tokens.css')).toContain("@import './scrollbars.css'");
  });

  it('styles every scroller, not a hand-picked list', () => {
    expect(scrollCss).toContain('*::-webkit-scrollbar');
  });

  it('removes the stepper arrows that betray the platform widget', () => {
    const match = scrollCss.match(/\*::-webkit-scrollbar-button\s*\{[^}]*\}/);
    expect(match).not.toBeNull();
    expect(match?.[0]).toContain('display: none');
  });

  it('keeps the thumb reachable with a minimum length', () => {
    expect(scrollCss).toContain('min-height: var(--size-scrollbar-thumb-min)');
    expect(scrollCss).toContain('min-width: var(--size-scrollbar-thumb-min)');
  });

  it('spends no literal sizes or colours outside the token layer', () => {
    const declarations = [...scrollCss.matchAll(/(?<![\w-])(width|height|background|color):\s*([^;]+);/g)];
    expect(declarations.length).toBeGreaterThan(0);
    for (const [, prop, value] of declarations) {
      if (value.includes('transparent') || value.includes('content-box') || value === '0') {
        continue;
      }
      expect(value, prop).toContain('var(--');
    }
  });

  it('reserves the standards property for engines without the WebKit pseudo-element', () => {
    const guarded = scrollCss.match(/@supports not selector\(::-webkit-scrollbar\)\s*\{[\s\S]*?\n\}/);
    expect(guarded).not.toBeNull();
    expect(guarded?.[0]).toContain('scrollbar-width: thin');
    const outside = scrollCss.replace(guarded?.[0] ?? '', '');
    expect(outside).not.toContain('scrollbar-width');
  });

  it('gives both themes a thumb that darkens on hover and press', () => {
    for (const theme of ['tokens.light.css', 'tokens.dark.css']) {
      const css = themeFile(theme);
      for (const token of [
        '--color-scroll-thumb',
        '--color-scroll-thumb-hover',
        '--color-scroll-thumb-active'
      ]) {
        expect(css, `${theme} ${token}`).toContain(token);
      }
    }
  });
});

describe('decorative overlays never swallow pointer input', () => {
  it('exempts the time-axis backdrop so the scene scrollbar stays reachable', () => {
    const css = readFileSync(join(srcDir, 'app', 'consoleScene.css'), 'utf-8');
    expect(css).toContain('.time-scale > *:not(.time-scale-backdrop)');
  });
});

describe('the console scrolls instead of crushing its content', () => {
  const consoleCss = readFileSync(join(srcDir, 'app', 'console.css'), 'utf-8');

  it('holds a minimum width so a narrow window scrolls sideways', () => {
    const block = consoleCss.match(/\.app\.console \{[^}]*\}/)?.[0] ?? '';
    expect(block).toContain('min-width: var(--size-console-min)');
  });

  it('keeps that floor in the token layer, not as a literal', () => {
    expect(themeFile('tokens.light.css')).toMatch(/--size-console-min:\s*\d+px/);
  });

  it('never locks the document itself against horizontal scrolling', () => {
    const base = readFileSync(join(srcDir, 'styles.css'), 'utf-8');
    expect(base).not.toMatch(/overflow-x:\s*hidden/);
  });
});

describe('text on a group fill stays readable in every group and theme', () => {
  const themes = [
    { name: 'light', css: themeFile('tokens.light.css') },
    { name: 'dark', css: themeFile('tokens.dark.css') }
  ];

  for (const theme of themes) {
    it(`${theme.name}: white and muted cap text clear 4.5:1 over the scrim`, () => {
      const scrim = resolve(theme.css, '--color-fill-scrim-mid', [0, 0, 0]);
      const alpha = Number(readToken(theme.css, '--color-fill-scrim-mid').match(/[\d.]+(?=\s*\)$)/)?.[0]);
      expect(alpha).toBeGreaterThan(0);
      const fills = [1, 2, 3, 4, 5, 6].map((n) => resolve(theme.css, `--color-group-${n}`, [255, 255, 255]));
      expect(fills).toHaveLength(6);
      const white = resolve(theme.css, '--color-on-fill', [0, 0, 0]);
      for (const fill of fills) {
        const bg = flatten([0, 0, 0], fill, alpha);
        expect(contrast(white, bg)).toBeGreaterThanOrEqual(4.5);
        expect(contrast(flatten(white, bg, 0.94), bg)).toBeGreaterThanOrEqual(4.5);
      }
      expect(scrim).toBeDefined();
    });
  }
});
