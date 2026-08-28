import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import type { AblationFile, NpvFile } from '../../api/types';
import { formatNumber, formatPercent } from '../../ui/format';
import { isAblationFile } from '../../data';
import { dictionaries } from '../../i18n/dictionaries';
import { I18nProvider } from '../../i18n/I18nContext';
import { TimelineProvider } from '../../state/TimelineContext';
import { coverageOf, stateOf, toEntries } from './ablation';
import {
  isNumericAblationKey,
  sortAblationEntries,
  type AblationSortKey
} from './ablationSorting';
import { NpvRank } from './NpvRank';

const { ru } = dictionaries;

const ablationFixture: AblationFile = {
  npv_total: 1000,
  rules: [
    { rule: 'R0', enabled: true, delta_npv: 300, share: 0.3 },
    { rule: 'R1', enabled: true, delta_npv: 200, share: 0.2 },
    { rule: 'R2', enabled: true, delta_npv: null, share: null },
    { rule: 'R5', enabled: true, delta_npv: 0, share: 0 },
    {
      rule: 'R7',
      enabled: false,
      delta_npv: null,
      share: null,
      disabled_reason: 'UPLIFT_NOT_MEASURED'
    }
  ]
};

const npvFixture: NpvFile = {
  wells: [{ well: '10', pre_tax: 1000, with_allocated_tax: 900 }],
  total: { pre_tax: 1000, with_allocated_tax: 900 },
  npv_methodology: 900
};

const withProviders = (node: ReactNode) => (
  <I18nProvider>
    <TimelineProvider>{node}</TimelineProvider>
  </I18nProvider>
);

const mockFetch = () => {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string) => {
      const payload = url.includes('ablation') ? ablationFixture : npvFixture;
      return Promise.resolve({ ok: true, json: () => Promise.resolve(payload) });
    })
  );
};

const renderView = async () => {
  const view = render(withProviders(<NpvRank />));
  await waitFor(() =>
    expect(
      view.container.querySelectorAll('.abl-table tbody tr[data-rule-id]')
    ).toHaveLength(ablationFixture.rules.length)
  );
  return view;
};

const ruleRow = (container: HTMLElement, rule: string): HTMLElement => {
  const row = container.querySelector(`.abl-table tbody tr[data-rule-id="${rule}"]`);
  expect(row).not.toBeNull();
  return row as HTMLElement;
};

beforeEach(() => {
  localStorage.clear();
  mockFetch();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('ablation state mapping', () => {
  it('separates an unmeasured rule from a measured zero and from a disabled rule', () => {
    const states = toEntries(ablationFixture.rules).map((entry) => entry.state);
    expect(states).toEqual(['measured', 'measured', 'unmeasured', 'zero', 'disabled']);
  });

  it('calls a null delta unmeasured even when the rule is enabled', () => {
    expect(stateOf({ rule: 'R6', enabled: true, delta_npv: null, share: null })).toBe(
      'unmeasured'
    );
  });

  it('accepts the shipped artifact shape and rejects a broken one', () => {
    expect(isAblationFile(ablationFixture)).toBe(true);
    expect(isAblationFile({ npv_total: 1, rules: [] })).toBe(false);
    expect(isAblationFile({ npv_total: 1, rules: [{ rule: 'R0' }] })).toBe(false);
  });
});

describe('ablation fixture consistency', () => {
  it('keeps the measured shares consistent with the deltas and the total', () => {
    for (const rule of ablationFixture.rules) {
      if (rule.delta_npv === null || rule.share === null) {
        continue;
      }
      expect(rule.share).toBeCloseTo(rule.delta_npv / ablationFixture.npv_total, 6);
    }
  });

  it('keeps the sum of measured shares within the total', () => {
    const sum = ablationFixture.rules.reduce((acc, rule) => acc + (rule.share ?? 0), 0);
    expect(sum).toBeLessThanOrEqual(1);
    expect(sum).toBeCloseTo(0.5, 6);
  });
});

const shipped = JSON.parse(
  readFileSync(join(process.cwd(), 'public', 'data', 'ablation.json'), 'utf-8')
) as unknown;

describe('shipped ablation artifact', () => {
  it('passes the validator', () => {
    expect(isAblationFile(shipped)).toBe(true);
  });

  it('keeps every measured share consistent with its delta and the run total', () => {
    const file = shipped as AblationFile;
    const measured = file.rules.filter((rule) => rule.delta_npv !== null);
    expect(measured.length).toBeGreaterThan(0);
    for (const rule of measured) {
      expect(rule.share, rule.rule).not.toBeNull();
      expect(rule.share as number, rule.rule).toBeCloseTo(
        (rule.delta_npv as number) / file.npv_total,
        6
      );
    }
  });

  it('keeps the sum of measured shares inside the run total', () => {
    const file = shipped as AblationFile;
    const sum = file.rules.reduce((acc, rule) => acc + (rule.share ?? 0), 0);
    const deltas = file.rules.reduce((acc, rule) => acc + (rule.delta_npv ?? 0), 0);
    expect(sum).toBeGreaterThan(0);
    expect(sum).toBeLessThanOrEqual(1);
    expect(sum).toBeCloseTo(deltas / file.npv_total, 5);
  });

  it('carries all three cases: measured, measured zero, unmeasured and disabled', () => {
    const file = shipped as AblationFile;
    const states = new Set(file.rules.map(stateOf));
    expect(states.has('measured')).toBe(true);
    expect(states.has('zero')).toBe(true);
    expect(states.has('unmeasured')).toBe(true);
    expect(states.has('disabled')).toBe(true);
  });
});

describe('AblationTable rendering', () => {
  it('shows "not measured" instead of zero when the measurement is absent', async () => {
    const { container } = await renderView();
    const row = ruleRow(container, 'R2');
    expect(row.getAttribute('data-state')).toBe('unmeasured');
    expect(row.textContent).toContain(ru['npv.ablation.unmeasured']);
    expect(row.textContent).not.toContain(ru['npv.ablation.zero']);
  });

  it('calls a measured zero a result, not an empty cell', async () => {
    const { container } = await renderView();
    const row = ruleRow(container, 'R5');
    expect(row.getAttribute('data-state')).toBe('zero');
    expect(row.textContent).toContain(ru['npv.ablation.zero']);
    expect(row.textContent).toContain(ru['npv.ablation.zeroHint']);
    expect(row.textContent).not.toContain(ru['npv.ablation.unmeasured']);
  });

  it('keeps a disabled rule distinguishable from a rule with zero contribution', async () => {
    const { container } = await renderView();
    const disabled = ruleRow(container, 'R7');
    const zero = ruleRow(container, 'R5');
    expect(disabled.getAttribute('data-state')).toBe('disabled');
    expect(zero.getAttribute('data-state')).toBe('zero');
    expect(disabled.querySelector('.abl-flag')?.textContent).toBe(
      ru['npv.ablation.flag.off']
    );
    expect(disabled.textContent).toContain(
      ru['npv.ablation.disabledReason.UPLIFT_NOT_MEASURED']
    );
    expect(zero.querySelector('.abl-flag')).toBeNull();
    expect(zero.textContent).toContain(ru['npv.ablation.zeroHint']);
  });

  it('renders the rule statement in field language and the total from the artifact', async () => {
    const { container } = await renderView();
    expect(ruleRow(container, 'R1').textContent).toContain(
      ru['npv.ablation.rule.R1.statement']
    );
    expect(screen.getByTestId('abl-total').textContent).toBe(
      formatNumber('ru', ablationFixture.npv_total)
    );
    expect(container.querySelector('.abl-table')).not.toBeNull();
  });

  it('prints the share from the artifact without recomputing it', async () => {
    const { container } = await renderView();
    const cell = ruleRow(container, 'R0');
    expect(cell.querySelector('.abl-share-value')?.textContent).toBe(
      formatPercent('ru', 0.3)
    );
    expect(cell.querySelector('.abl-delta')?.textContent).toBe(formatNumber('ru', 300));
    expect(ruleRow(container, 'R2').querySelector('.abl-bar')).toBeNull();
  });

  it('scales the bars against the strongest rule so the ranking stays readable', async () => {
    const { container } = await renderView();
    const ratioOf = (rule: string): string =>
      (ruleRow(container, rule).querySelector('.abl-bar') as HTMLElement).style.getPropertyValue(
        '--abl-bar-ratio'
      );

    expect(ratioOf('R0')).toBe('1');
    expect(Number(ratioOf('R1'))).toBeCloseTo(200 / 300, 6);
  });
});

describe('ablation coverage is stated in the interface', () => {
  it('reports how much of the total the measured shares actually explain', async () => {
    await renderView();
    const line = screen.getByTestId('abl-coverage').textContent ?? '';
    const measured = ablationFixture.rules.filter((rule) => rule.share !== null);
    const accounted = measured.reduce((acc, rule) => acc + (rule.share as number), 0);

    expect(line).toContain(formatPercent('ru', accounted));
    expect(line).toContain(String(measured.length));
    expect(line).toContain(String(ablationFixture.rules.length));
  });

  it('names the unmeasured rules as an unexplained remainder rather than hiding them', async () => {
    await renderView();
    const line = screen.getByTestId('abl-coverage').textContent ?? '';
    const unmeasured = ablationFixture.rules.filter((rule) => rule.share === null).length;

    expect(unmeasured).toBeGreaterThan(0);
    expect(line).toContain(String(unmeasured));
  });

  it('keeps the never-measured rules at the bottom instead of among the results', async () => {
    const { container } = await renderView();
    const order = [...container.querySelectorAll('.abl-table tbody tr[data-rule-id]')].map(
      (row) => (row as HTMLElement).dataset.ruleId
    );

    expect(order.slice(-2).sort()).toEqual(['R2', 'R7']);
  });

  it('counts a measured zero as accounted for, not as missing', () => {
    const coverage = coverageOf(toEntries(ablationFixture.rules));
    const zeroRules = ablationFixture.rules.filter((rule) => rule.share === 0).length;

    expect(zeroRules).toBeGreaterThan(0);
    expect(coverage.measured).toBe(
      ablationFixture.rules.filter((rule) => rule.share !== null).length
    );
    expect(coverage.unmeasured).toBe(
      ablationFixture.rules.filter((rule) => rule.share === null).length
    );
    expect(coverage.accountedShare).toBeCloseTo(0.5, 6);
  });

  it('takes the shares from the artifact instead of deriving them from the deltas', () => {
    const tampered = ablationFixture.rules.map((rule) =>
      rule.rule === 'R0' ? { ...rule, share: 0.42 } : rule
    );
    const coverage = coverageOf(toEntries(tampered));

    expect(coverage.accountedShare).toBeCloseTo(0.62, 6);
  });
});

describe('ablation states its coverage as a figure, not as buried prose', () => {
  it('reads the explained share out of the summary instead of a wrapped sentence', async () => {
    const { container } = await renderView();
    const summary = container.querySelector('.abl-summary') as HTMLElement;

    expect(summary.textContent).toContain(formatPercent('ru', 0.5));
    expect(container.querySelector('.abl-coverage-gap')).toBeNull();
  });

  it('counts the measured rules against the total instead of implying all were', async () => {
    const { container } = await renderView();
    const measured = ablationFixture.rules.filter((rule) => rule.share !== null).length;
    const stat = container.querySelector('.abl-summary-stat') as HTMLElement;

    expect(stat.textContent).toContain(String(measured));
    expect(stat.textContent).toContain(String(ablationFixture.rules.length));
  });

  it('says plainly that the rest of the total is unexplained', async () => {
    const { container } = await renderView();
    const unmeasured = ablationFixture.rules.filter((rule) => rule.share === null).length;
    const gap = container.querySelector('.abl-summary-gap') as HTMLElement;

    expect(unmeasured).toBeGreaterThan(0);
    expect(gap.textContent).toBe(
      ru['npv.ablation.summary.gap'].replace('{count}', String(unmeasured))
    );
  });

  it('does not claim an unexplained remainder when every rule was measured', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) =>
        Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve(
              url.includes('ablation')
                ? {
                    npv_total: 1000,
                    rules: [{ rule: 'R0', enabled: true, delta_npv: 300, share: 0.3 }]
                  }
                : npvFixture
            )
        })
      )
    );
    const { container } = render(withProviders(<NpvRank />));
    await waitFor(() =>
      expect(container.querySelector('.abl-summary-gap')).not.toBeNull()
    );

    expect(container.querySelector('.abl-summary-gap')?.textContent).toBe(
      ru['npv.ablation.summary.gapNone']
    );
  });

  it('names the rule worth the most money without making the reader sort the table', async () => {
    const { container } = await renderView();
    const top = container.querySelector('.abl-summary-top') as HTMLElement;

    expect(top.textContent).toContain('R0');
    expect(top.textContent).toContain(ru['npv.ablation.rule.R0.name']);
  });

  it('drops the duplicated heading when the table is the whole page', () => {
    const css = readFileSync(
      join(process.cwd(), 'src', 'views', 'NpvRank', 'AblationTable.css'),
      'utf-8'
    );
    const hidden = css.match(
      /\.abl\[data-standalone='true'\] \.abl-title\s*\{[^}]*\}/
    );
    expect(hidden).not.toBeNull();
    expect((hidden as RegExpMatchArray)[0]).toContain('clip-path');
  });

  it('caps only the prose, never the table wrapper', async () => {
    const { container } = await renderView();
    const wrap = container.querySelector('.abl-table-wrap') as HTMLElement;
    expect(wrap.style.maxWidth).toBe('');

    const css = readFileSync(
      join(process.cwd(), 'src', 'views', 'NpvRank', 'AblationTable.css'),
      'utf-8'
    );
    const wrapBlock = css.match(/\.abl-table-wrap\s*\{[^}]*\}/);
    expect(wrapBlock).not.toBeNull();
    expect((wrapBlock as RegExpMatchArray)[0]).not.toContain('--size-prose-max');
  });
});

describe('ablation rows reveal in order', () => {
  it('numbers every row so the stagger follows the table order', async () => {
    const { container } = await renderView();
    const indices = [
      ...container.querySelectorAll('.abl-table tbody tr[data-rule-id]')
    ].map((row) => (row as HTMLElement).style.getPropertyValue('--abl-row-index'));

    expect(indices).toHaveLength(ablationFixture.rules.length);
    expect(indices.every((index) => index !== '')).toBe(true);
  });

  it('keeps the stagger delay after the animation shorthand that would reset it', () => {
    const css = readFileSync(
      join(process.cwd(), 'src', 'views', 'NpvRank', 'AblationTable.css'),
      'utf-8'
    );
    const block = css.match(/\.abl-table tbody tr \{[^}]*\}/)?.[0] ?? '';

    expect(block).toContain('animation-delay');
    expect(block.indexOf('animation:')).toBeLessThan(block.indexOf('animation-delay'));
    expect(block).toContain('--abl-row-index');
  });

  it('turns the row reveal off when the reader asks for reduced motion', () => {
    const css = readFileSync(
      join(process.cwd(), 'src', 'views', 'NpvRank', 'AblationTable.css'),
      'utf-8'
    );
    const reduced = css.match(
      /@media \(prefers-reduced-motion: reduce\)\s*\{[\s\S]*?\n\}/
    );
    expect(reduced).not.toBeNull();
    expect((reduced as RegExpMatchArray)[0]).toContain('animation: none');
  });
});

const LABELS = {
  name: (rule: string) => ru[`npv.ablation.rule.${rule}.name`] ?? rule,
  statement: (rule: string) => ru[`npv.ablation.rule.${rule}.statement`] ?? ''
};

const order = (key: AblationSortKey, dir: 'asc' | 'desc'): string[] =>
  sortAblationEntries(toEntries(ablationFixture.rules), key, dir, LABELS).map(
    (entry) => entry.rule
  );

describe('ablation table sorts on every column', () => {
  it('ranks by the money a rule is worth, biggest first, by default', () => {
    expect(order('delta', 'desc').slice(0, 3)).toEqual(['R0', 'R1', 'R5']);
  });

  it('reverses that ranking without floating the unmeasured rules to the top', () => {
    const asc = order('delta', 'asc');
    expect(asc.slice(0, 3)).toEqual(['R5', 'R1', 'R0']);
    expect(asc.slice(-2).sort()).toEqual(['R2', 'R7']);
  });

  it('keeps the unmeasured rules last in both directions', () => {
    for (const dir of ['asc', 'desc'] as const) {
      for (const key of ['rule', 'name', 'statement', 'delta', 'share'] as const) {
        expect(order(key, dir).slice(-2).sort(), `${key}/${dir}`).toEqual(['R2', 'R7']);
      }
    }
  });

  it('sorts the code column as a code and the name column by its text', () => {
    expect(order('rule', 'asc').slice(0, 3)).toEqual(['R0', 'R1', 'R5']);
    const byName = order('name', 'asc').slice(0, 3);
    const names = byName.map((rule) => LABELS.name(rule));
    expect([...names]).toEqual([...names].sort((a, b) => a.localeCompare(b)));
  });

  it('sorts the share column the same way it sorts the money', () => {
    expect(order('share', 'desc').slice(0, 3)).toEqual(order('delta', 'desc').slice(0, 3));
  });

  it('treats only the money columns as numeric', () => {
    expect(isNumericAblationKey('delta')).toBe(true);
    expect(isNumericAblationKey('share')).toBe(true);
    expect(isNumericAblationKey('rule')).toBe(false);
    expect(isNumericAblationKey('name')).toBe(false);
  });

  it('leaves every rule in the table whatever the sort', () => {
    for (const key of ['rule', 'name', 'statement', 'delta', 'share'] as const) {
      expect(new Set(order(key, 'asc')).size).toBe(ablationFixture.rules.length);
    }
  });
});

describe('ablation table sorting is reachable from the interface', () => {
  it('gives every column a sort button that reports its direction', async () => {
    const { container } = await renderView();
    const heads = [...container.querySelectorAll('.abl-table thead th')];

    expect(heads).toHaveLength(5);
    expect(heads.every((th) => th.querySelector('.abl-sort-button') !== null)).toBe(true);
    const active = heads.filter((th) => th.getAttribute('aria-sort') !== 'none');
    expect(active).toHaveLength(1);
    expect(active[0].getAttribute('aria-sort')).toBe('descending');
  });

  it('flips the direction when the reader clicks the active column again', async () => {
    const { container } = await renderView();
    const rows = () =>
      [...container.querySelectorAll('.abl-table tbody tr[data-rule-id]')].map(
        (row) => (row as HTMLElement).dataset.ruleId
      );

    const before = rows();
    const head = [...container.querySelectorAll('.abl-table thead th')].find(
      (th) => th.getAttribute('aria-sort') !== 'none'
    ) as HTMLElement;
    fireEvent.click(head.querySelector('.abl-sort-button') as HTMLElement);

    expect(head.getAttribute('aria-sort')).toBe('ascending');
    expect(rows()).not.toEqual(before);
  });

  it('replays the row reveal so a re-sort is visible, not an instant swap', async () => {
    const { container } = await renderView();
    const bodyKeyBefore = container.querySelector('.abl-table tbody');
    const first = () =>
      (
        container.querySelector('.abl-table tbody tr[data-rule-id]') as HTMLElement
      ).dataset.ruleId;

    const before = first();
    fireEvent.click(
      container.querySelectorAll('.abl-table thead th')[1].querySelector(
        '.abl-sort-button'
      ) as HTMLElement
    );

    expect(first()).not.toBe(before);
    expect(container.querySelector('.abl-table tbody')).not.toBe(bodyKeyBefore);
  });

  it('moves the sort to another column when that column is clicked', async () => {
    const { container } = await renderView();
    const heads = [...container.querySelectorAll('.abl-table thead th')];
    fireEvent.click(heads[0].querySelector('.abl-sort-button') as HTMLElement);

    expect(heads[0].getAttribute('aria-sort')).toBe('ascending');
    expect(heads.filter((th) => th.getAttribute('aria-sort') !== 'none')).toHaveLength(1);
  });
});

describe('ablation copy survives a count of any size', () => {
  const dict = JSON.parse(
    readFileSync(join(process.cwd(), 'src', 'i18n', 'ru', 'npv.json'), 'utf-8')
  ) as Record<string, string>;

  it('never glues a Russian noun straight onto a count it must agree with', () => {
    for (const [key, text] of Object.entries(dict)) {
      expect(/\{count\}\s+[А-Яа-яЁё]/.test(text), `${key}: ${text}`).toBe(false);
    }
  });

  it('keeps the measured-zero cell short enough to read as a number', () => {
    expect(dict['ablation.zero'].length).toBeLessThanOrEqual(3);
  });

  it('explains the zero in the statement column rather than in the number', () => {
    expect(dict['ablation.zeroHint']).toContain('кандидат на удаление');
  });
});
