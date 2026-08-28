import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const read = (...parts: string[]): string =>
  readFileSync(join(process.cwd(), 'src', ...parts), 'utf-8');

const blockOf = (css: string, selector: string): string => {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const match = css.match(new RegExp(`${escaped}\\s*\\{[^}]*\\}`));
  expect(match, `${selector} exists`).not.toBeNull();
  return match?.[0] ?? '';
};

describe('the well card floats over the scene instead of squeezing it', () => {
  const shell = read('app', 'console.css');

  it('never gives the card a grid column that would resize the content', () => {
    expect(shell).not.toMatch(/\[data-inspector='open'\]\s*\{[^}]*grid-template-columns/);
    expect(blockOf(shell, '.console-area-inspector')).toContain('position: fixed');
  });

  it('lets clicks through everywhere except the card itself', () => {
    expect(blockOf(shell, '.console-area-inspector')).toContain('pointer-events: none');
    expect(blockOf(shell, '.console-area-inspector > *')).toContain('pointer-events: auto');
  });
});

describe('the dimmed backdrop leaves the transport usable', () => {
  const shell = read('app', 'console.css');

  it('stops above the player instead of covering it', () => {
    const scrim = blockOf(shell, '.console-scrim');
    expect(scrim).toMatch(/inset:\s*var\(--h-header\)[^;]*var\(--h-player-opaque\)/);
  });

  it('reserves the same strip for the card as it does for itself', () => {
    const area = blockOf(shell, '.console-area-inspector');
    expect(area).toContain('var(--h-player-opaque)');
  });

  it('measures the collapsed player from the document root the backdrop lives in', () => {
    expect(shell).toMatch(/:root:has\([^)]*data-axis='collapsed'[^)]*\)\s*\{[^}]*--h-player-opaque/);
  });

  it('spends no literal pixels on either reserve', () => {
    for (const selector of ['.console-scrim', '.console-area-inspector']) {
      const block = blockOf(shell, selector);
      const sizing = [...block.matchAll(/(?:inset|padding):\s*([^;]+);/g)].map((m) => m[1]);
      expect(sizing.length, selector).toBeGreaterThan(0);
      for (const value of sizing) {
        expect(value, selector).not.toMatch(/\d+px/);
      }
    }
  });
});

describe('the card announces itself with motion, not a jump', () => {
  const css = read('ui', 'Inspector', 'Inspector.css');
  const shell = read('app', 'console.css');

  it('slides in from the edge it is anchored to', () => {
    const frames = css.match(/@keyframes inspector-in\s*\{[\s\S]*?\n\}/)?.[0] ?? '';
    expect(frames).toContain('translateX');
  });

  it('runs a real exit animation instead of a reversed one the browser skips', () => {
    for (const [sheet, selector, frames] of [
      [css, ".inspector[data-closing='true']", 'inspector-out'],
      [shell, ".console-scrim[data-closing='true']", 'console-scrim-out']
    ] as const) {
      const block = blockOf(sheet, selector);
      expect(block, selector).toContain(frames);
      expect(block, `${selector} must not rely on reverse`).not.toContain('reverse');
      expect(sheet, frames).toContain(`@keyframes ${frames}`);
    }
  });

  it('keeps the unmount delay in step with the exit animation', () => {
    const hook = read('ui', 'Inspector', 'useDeferredClose.ts');
    const delay = Number(hook.match(/CLOSE_MS\s*=\s*(\d+)/)?.[1]);
    const tokens = read('theme', 'tokens.light.css');
    const state = Number(tokens.match(/--duration-state:\s*(\d+)ms/)?.[1]);
    expect(delay).toBeGreaterThanOrEqual(state);
    expect(delay).toBeLessThanOrEqual(state * 2);
  });

  it('holds still when the viewer asked for less motion', () => {
    for (const sheet of [css, shell]) {
      const guard = sheet.match(/@media \(prefers-reduced-motion: reduce\)\s*\{[\s\S]*?\n\}/)?.[0];
      expect(guard).toBeDefined();
      expect(guard).toContain('animation: none');
    }
  });
});

describe('the close button is centred and big enough to hit', () => {
  const css = read('ui', 'Inspector', 'Inspector.css');

  it('clears the asymmetric padding a browser gives every button', () => {
    const block = blockOf(css, '.inspector-close');
    expect(block).toMatch(/padding:\s*0\s*;/);
  });

  it('centres the glyph by layout rather than by guessed padding', () => {
    const block = blockOf(css, '.inspector-close');
    expect(block).toContain('place-items: center');
  });

  it('grows the hit area to the minimum a finger needs', () => {
    const target = blockOf(css, '.inspector-close::after');
    expect(target).toContain('var(--size-tap-min)');
    const tokens = read('theme', 'tokens.light.css');
    const size = Number(tokens.match(/--size-tap-min:\s*(\d+)px/)?.[1]);
    expect(size).toBeGreaterThanOrEqual(44);
  });
});

describe('the inspector is only ever a well card now', () => {
  it('carries no scenario branch to fall out of step with the library', () => {
    const shell = read('ui', 'Inspector', 'ConsoleInspector.tsx');
    expect(shell).not.toContain('scenario');
    expect(shell).not.toContain('Scenario');
  });

  it('describes a single inspector context instead of a union', () => {
    const types = read('ui', 'Inspector', 'InspectorContext.ts');
    expect(types).not.toContain('ScenarioInspectorContext');
  });
});
