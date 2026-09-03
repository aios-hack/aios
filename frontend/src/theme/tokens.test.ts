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

const rootDir = process.cwd();

const brandAsset = (name: string): string =>
  readFileSync(join(rootDir, name), 'utf-8');

const tokenValue = (block: string, token: string): string | null => {
  const match = block.match(new RegExp(`${token}:\\s*(#[0-9a-fA-F]{3,8})\\s*;`));
  return match === null ? null : match[1].toLowerCase();
};

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

  it('paints the shell theme colour with the accent token, not a drifting copy', () => {
    const accent = tokenValue(themeFile('tokens.light.css'), '--color-accent');
    expect(accent).not.toBeNull();
    expect(brandAsset('index.html').toLowerCase()).toContain(
      `content="${accent as string}"`
    );
  });

  it('draws the favicon in the console palette the brand logo uses on dark', () => {
    const favicon = brandAsset(join('public', 'favicon.svg')).toLowerCase();
    const darkSurface = tokenValue(themeFile('tokens.dark.css'), '--color-surface');

    expect(favicon).toContain(darkSurface as string);
    expect(favicon).toContain('#9480f1');
  });

  it('keeps the dark theme-color in step with the dark surface token', () => {
    const surface = tokenValue(themeFile('tokens.dark.css'), '--color-surface');
    expect(surface).not.toBeNull();
    expect(brandAsset('index.html').toLowerCase()).toContain(
      `content="${surface as string}"`
    );
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

  it('scales the corner radii monotonically so a card reads rounder than a control', () => {
    const radii = Object.fromEntries(
      [...css.matchAll(/--radius-(?!pill)([\w-]*):\s*(\d+)px/g)].map((m) => [m[1], Number(m[2])])
    );
    for (const name of ['sm', 'md', 'lg', 'xl']) {
      expect(radii, name).toHaveProperty(name);
    }
    expect(radii.sm).toBeLessThan(radii.md);
    expect(radii.md).toBeLessThan(radii.lg);
    expect(radii.lg).toBeLessThan(radii.xl);
    expect(radii.xl).toBeLessThanOrEqual(18);
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

const labOf = ([r, g, b]: number[]): number[] => {
  const [R, G, B] = [channel(r), channel(g), channel(b)];
  const x = (0.4124 * R + 0.3576 * G + 0.1805 * B) / 0.95047;
  const y = 0.2126 * R + 0.7152 * G + 0.0722 * B;
  const z = (0.0193 * R + 0.1192 * G + 0.9505 * B) / 1.08883;
  const f = (t: number): number => (t > 0.008856 ? Math.cbrt(t) : 7.787 * t + 16 / 116);
  return [116 * f(y) - 16, 500 * (f(x) - f(y)), 200 * (f(y) - f(z))];
};

const lightness = (rgb: number[]): number => labOf(rgb)[0];

const chroma = (rgb: number[]): number => {
  const [, a, b] = labOf(rgb);
  return Math.hypot(a, b);
};

const saturation = ([r, g, b]: number[]): number => {
  const mx = Math.max(r, g, b);
  return mx === 0 ? 0 : (mx - Math.min(r, g, b)) / mx;
};

const RAMP_STEPS = 21;

const rampSamples = (from: number[], to: number[]): number[][] =>
  Array.from({ length: RAMP_STEPS }, (_, i) => {
    const t = i / (RAMP_STEPS - 1);
    return from.map((c, k) => c + (to[k] - c) * t);
  });

const hueOf = ([r, g, b]: number[]): number => {
  const [mx, mn] = [Math.max(r, g, b), Math.min(r, g, b)];
  const d = mx - mn;
  if (d === 0) {
    return 0;
  }
  const raw =
    mx === r ? 60 * (((g - b) / d) % 6) : mx === g ? 60 * ((b - r) / d + 2) : 60 * ((r - g) / d + 4);
  return raw < 0 ? raw + 360 : raw;
};

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

describe('a colour ramp reads without relying on hue alone', () => {
  for (const name of ['tokens.light.css', 'tokens.dark.css']) {
    it(`${name}: the watercut ends differ in lightness, not just in hue`, () => {
      const css = themeFile(name);
      const dry = resolve(css, '--scale-watercut-0', [255, 255, 255]);
      const wet = resolve(css, '--scale-watercut-1', [255, 255, 255]);
      expect(contrast(dry, wet)).toBeGreaterThanOrEqual(2);
    });
  }

  it('light: the watercut ramp keeps its colour without glaring', () => {
    const css = themeFile('tokens.light.css');
    const dry = resolve(css, '--scale-watercut-0', [255, 255, 255]);
    const wet = resolve(css, '--scale-watercut-1', [255, 255, 255]);
    const samples = rampSamples(dry, wet);
    const meanChroma = samples.reduce((sum, rgb) => sum + chroma(rgb), 0) / samples.length;
    expect(meanChroma).toBeGreaterThanOrEqual(15);
    expect(meanChroma).toBeLessThanOrEqual(22);
    for (const rgb of samples) {
      expect(chroma(rgb)).toBeLessThanOrEqual(42);
    }
  });

  it('light: the watercut ramp reads warm at the dry end and cool at the wet end', () => {
    const css = themeFile('tokens.light.css');
    const dry = resolve(css, '--scale-watercut-0', [255, 255, 255]);
    const wet = resolve(css, '--scale-watercut-1', [255, 255, 255]);
    const meanSaturation =
      rampSamples(dry, wet).reduce((sum, rgb) => sum + saturation(rgb), 0) / RAMP_STEPS;
    expect(meanSaturation).toBeGreaterThanOrEqual(0.24);
    expect(meanSaturation).toBeLessThanOrEqual(0.36);
    expect(hueOf(dry)).toBeGreaterThanOrEqual(20);
    expect(hueOf(dry)).toBeLessThanOrEqual(50);
    expect(hueOf(wet)).toBeGreaterThanOrEqual(170);
    expect(hueOf(wet)).toBeLessThanOrEqual(220);
  });

  it('light: the watercut ramp climbs in lightness the whole way, so it reads in greyscale', () => {
    const css = themeFile('tokens.light.css');
    const dry = resolve(css, '--scale-watercut-0', [255, 255, 255]);
    const wet = resolve(css, '--scale-watercut-1', [255, 255, 255]);
    const samples = rampSamples(dry, wet);
    const lightnesses = samples.map(lightness);
    for (let i = 1; i < lightnesses.length; i += 1) {
      expect(lightnesses[i]).toBeGreaterThan(lightnesses[i - 1]);
    }
    expect(lightnesses[lightnesses.length - 1] - lightnesses[0]).toBeGreaterThanOrEqual(25);
  });
});

describe('a meaning-bearing colour never washes into the page behind it', () => {
  const surfaces = ['--color-bg', '--color-surface', '--color-surface-sunken'];
  const carriers = [
    '--color-group-1',
    '--color-group-2',
    '--color-group-3',
    '--color-group-4',
    '--color-group-5',
    '--color-group-6',
    '--color-oil-strong',
    '--color-water',
    '--color-injection',
    '--color-layer-1',
    '--color-layer-2',
    '--color-ok',
    '--color-error',
    '--scale-ratio-low',
    '--scale-ratio-mid',
    '--scale-ratio-high'
  ];

  for (const name of ['tokens.light.css', 'tokens.dark.css']) {
    const css = themeFile(name);
    for (const carrier of carriers) {
      it(`${name}: ${carrier} clears 3:1 on every surface`, () => {
        for (const surface of surfaces) {
          const bg = resolve(css, surface, [255, 255, 255]);
          expect(contrast(resolve(css, carrier, bg), bg), `${carrier} on ${surface}`).toBeGreaterThanOrEqual(3);
        }
      });
    }
  }

  it('light: the categorical groups carry real colour, not a pastel wash', () => {
    const css = themeFile('tokens.light.css');
    for (const n of [1, 2, 3, 4, 5, 6]) {
      const rgb = resolve(css, `--color-group-${n}`, [255, 255, 255]);
      expect(chroma(rgb), `group ${n} chroma`).toBeGreaterThanOrEqual(40);
      expect(chroma(rgb), `group ${n} chroma`).toBeLessThanOrEqual(85);
    }
  });
});

describe('the mode fills stay comfortable across a full-screen matrix', () => {
  const css = themeFile('tokens.light.css');
  const white = [255, 255, 255];

  it('light: production is the quiet field, because it fills most of the matrix', () => {
    const oil = resolve(css, '--color-oil', white);
    expect(saturation(oil)).toBeLessThanOrEqual(0.42);
    expect(chroma(oil)).toBeLessThanOrEqual(32);
    expect(lightness(oil)).toBeGreaterThanOrEqual(76);
  });

  it('light: injection is the smaller accent, so it may carry more weight', () => {
    const injection = resolve(css, '--color-injection', white);
    expect(saturation(injection)).toBeLessThanOrEqual(0.70);
    expect(chroma(injection)).toBeLessThanOrEqual(42);
  });

  it('light: the two mode fills differ in weight, not only in hue', () => {
    const oil = resolve(css, '--color-oil', white);
    const injection = resolve(css, '--color-injection', white);
    expect(lightness(oil) - lightness(injection)).toBeGreaterThanOrEqual(24);
    expect(contrast(oil, injection)).toBeGreaterThanOrEqual(2.6);
  });

  it('light: production reads warm and injection reads cool', () => {
    const oil = hueOf(resolve(css, '--color-oil', white));
    const injection = hueOf(resolve(css, '--color-injection', white));
    expect(oil).toBeGreaterThanOrEqual(20);
    expect(oil).toBeLessThanOrEqual(50);
    expect(injection).toBeGreaterThanOrEqual(190);
    expect(injection).toBeLessThanOrEqual(230);
  });

  it('light: a mode label uses an ink dark enough to read, never the pale fill', () => {
    const chronomapCss = readFileSync(
      join(srcDir, 'views', 'Chronomap', 'Chronomap.css'),
      'utf-8'
    );
    const block = chronomapCss.match(
      /\.chronomap-readout-mode\[data-mode='production'\]\s*\{[^}]*\}/
    )?.[0] ?? '';
    expect(block).toContain('color: var(--color-oil-strong)');
    for (const token of ['--color-oil-strong', '--color-injection-strong']) {
      for (const surface of ['--color-bg', '--color-surface', '--color-surface-sunken']) {
        const bg = resolve(css, surface, white);
        expect(contrast(resolve(css, token, bg), bg), `${token} on ${surface}`).toBeGreaterThanOrEqual(4.5);
      }
    }
  });

  it('light: a thin oil line never uses the pale matrix fill', () => {
    const tokensTs = readFileSync(join(srcDir, 'theme', 'tokens.ts'), 'utf-8');
    const wall = tokensTs.match(/wallMarkColors\s*=\s*\{[^}]*\}/)?.[0] ?? '';
    expect(wall).toContain("line: 'var(--color-oil-strong)'");
  });
});

describe('the step cursor separates itself from whatever cell it lands on', () => {
  const cellFills = (css: string): number[][] => {
    const dry = resolve(css, '--scale-watercut-0', [255, 255, 255]);
    const wet = resolve(css, '--scale-watercut-1', [255, 255, 255]);
    return [
      ...rampSamples(dry, wet),
      ...['--color-oil', '--color-injection', '--color-surface-sunken', '--color-plot-bg'].map(
        (token) => resolve(css, token, [255, 255, 255])
      )
    ];
  };

  for (const name of ['tokens.light.css', 'tokens.dark.css']) {
    it(`${name}: the ink and halo carry their own edge, whatever cell is underneath`, () => {
      const css = themeFile(name);
      const ink = resolve(css, '--color-cursor-ink', [255, 255, 255]);
      const halo = resolve(css, '--color-cursor-halo', [255, 255, 255]);
      expect(contrast(ink, halo)).toBeGreaterThanOrEqual(4.5);
    });

    it(`${name}: one of the two strokes always separates from the cell it covers`, () => {
      const css = themeFile(name);
      const ink = resolve(css, '--color-cursor-ink', [255, 255, 255]);
      const halo = resolve(css, '--color-cursor-halo', [255, 255, 255]);
      for (const fill of cellFills(css)) {
        const best = Math.max(contrast(ink, fill), contrast(halo, fill));
        expect(best).toBeGreaterThanOrEqual(3);
      }
    });
  }

  it('draws the cursor at full strength, never as a translucent wash over the cells', () => {
    const css = readFileSync(join(srcDir, 'views', 'Chronomap', 'Chronomap.css'), 'utf-8');
    const block = css.match(/\.chronomap-cursor\s*\{[^}]*\}/)?.[0] ?? '';
    expect(block).not.toMatch(/opacity:\s*0?\.\d/);
  });

  it('light: the cursor no longer borrows the wet end of the ramp', () => {
    const css = themeFile('tokens.light.css');
    expect(readToken(css, '--color-cursor-ink')).not.toBe(readToken(css, '--scale-watercut-1'));
  });
});

describe('text on a group fill stays readable in every group and theme', () => {
  const themes = [
    { name: 'light', css: themeFile('tokens.light.css') },
    { name: 'dark', css: themeFile('tokens.dark.css') }
  ];

  for (const theme of themes) {
    it(`${theme.name}: cap text clears 4.5:1 on every group fill without a scrim`, () => {
      const ink = resolve(theme.css, '--color-on-fill', [255, 255, 255]);
      const fills = [1, 2, 3, 4, 5, 6].map((n) =>
        resolve(theme.css, `--color-group-${n}`, [255, 255, 255])
      );
      expect(fills).toHaveLength(6);
      for (const fill of fills) {
        expect(contrast(ink, fill)).toBeGreaterThanOrEqual(4.5);
        expect(contrast(flatten(ink, fill, 0.9), fill)).toBeGreaterThanOrEqual(4.5);
      }
    });
  }

  it('paints a group the same colour in both themes so a site never changes identity', () => {
    const light = themeFile('tokens.light.css');
    const dark = themeFile('tokens.dark.css');
    for (const n of [1, 2, 3, 4, 5, 6]) {
      expect(readToken(dark, `--color-group-${n}`), `group ${n}`).toBe(
        readToken(light, `--color-group-${n}`)
      );
    }
  });

  it('spreads the six group hues apart so neighbours stay distinguishable', () => {
    const css = themeFile('tokens.light.css');
    const hues = [1, 2, 3, 4, 5, 6].map((n) => hueOf(resolve(css, `--color-group-${n}`, [255, 255, 255])));
    const sorted = [...hues].sort((a, b) => a - b);
    for (let i = 0; i < sorted.length; i += 1) {
      const next = i === sorted.length - 1 ? sorted[0] + 360 : sorted[i + 1];
      expect(next - sorted[i], `gap after hue ${sorted[i]}`).toBeGreaterThanOrEqual(30);
    }
  });

  it('keeps the accent clear of the injection blue so they never read as one colour', () => {
    for (const name of ['tokens.light.css', 'tokens.dark.css']) {
      const css = themeFile(name);
      const accent = hueOf(resolve(css, '--color-accent', [255, 255, 255]));
      const injection = hueOf(resolve(css, '--color-injection', [255, 255, 255]));
      const gap = Math.abs(accent - injection);
      expect(Math.min(gap, 360 - gap), name).toBeGreaterThanOrEqual(30);
    }
  });
});

describe('the Jarvis sphere inverts with the theme instead of borrowing the accent', () => {
  const light = themeFile('tokens.light.css');
  const dark = themeFile('tokens.dark.css');
  const sphereTokens = [
    '--color-jarvis-body',
    '--color-jarvis-pulse',
    '--color-jarvis-deep',
    '--color-jarvis-rim',
    '--color-jarvis-halo',
    '--color-jarvis-face',
    '--color-jarvis-spark',
    '--color-jarvis-vignette'
  ];

  it('names every sphere colour in both themes', () => {
    for (const token of sphereTokens) {
      expect(light, token).toContain(token);
      expect(dark, token).toContain(token);
    }
  });

  it('paints a blue body on the light face and an icy body on the dark face', () => {
    const lightBody = resolve(light, '--color-jarvis-body', [255, 255, 255]);
    const darkBody = resolve(dark, '--color-jarvis-body', [255, 255, 255]);
    expect(lightness(lightBody)).toBeLessThan(lightness(darkBody));
    const hue = hueOf(lightBody);
    expect(hue).toBeGreaterThanOrEqual(195);
    expect(hue).toBeLessThanOrEqual(225);
  });

  it('shares the light body with the injector blue so the sphere reads as water', () => {
    expect(readToken(light, '--color-jarvis-body')).toBe(readToken(light, '--color-graph-injector'));
  });

  for (const theme of [
    { name: 'light', css: light },
    { name: 'dark', css: dark }
  ]) {
    it(`${theme.name}: the body separates from the Jarvis face and the console background`, () => {
      for (const surface of ['--color-jarvis-face', '--color-bg']) {
        const bg = resolve(theme.css, surface, [255, 255, 255]);
        expect(contrast(resolve(theme.css, '--color-jarvis-body', bg), bg), surface).toBeGreaterThanOrEqual(3);
      }
    });

    it(`${theme.name}: the scene caption clears 4.5:1 on the Jarvis face`, () => {
      const face = resolve(theme.css, '--color-jarvis-face', [255, 255, 255]);
      for (const text of ['--color-text', '--color-text-muted']) {
        expect(contrast(resolve(theme.css, text, face), face), text).toBeGreaterThanOrEqual(4.5);
      }
    });

    it(`${theme.name}: the action ink clears 4.5:1 on every surface a card sits on`, () => {
      for (const surface of ['--color-surface', '--color-surface-sunken', '--color-jarvis-face']) {
        const bg = resolve(theme.css, surface, [255, 255, 255]);
        expect(
          contrast(resolve(theme.css, '--color-jarvis-ink', bg), bg),
          `${theme.name} ${surface}`
        ).toBeGreaterThanOrEqual(4.5);
      }
    });

    it(`${theme.name}: the pulse colour and the body colour never merge`, () => {
      const body = resolve(theme.css, '--color-jarvis-body', [255, 255, 255]);
      const pulse = resolve(theme.css, '--color-jarvis-pulse', [255, 255, 255]);
      expect(contrast(body, pulse)).toBeGreaterThanOrEqual(2);
    });
  }

  it('keeps the transition takts as duration tokens', () => {
    for (const token of [
      '--duration-jarvis-shrink',
      '--duration-jarvis-turn',
      '--duration-jarvis-settle',
      '--duration-jarvis-crossfade',
      '--stagger-orbit',
      '--perspective-stage'
    ]) {
      expect(light, token).toContain(token);
    }
    expect(readToken(light, '--duration-jarvis-turn')).toBe('600ms');
    expect(readToken(light, '--duration-jarvis-shrink')).toBe('220ms');
  });
});
