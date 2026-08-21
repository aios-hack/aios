import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import type { AblationFile, NpvFile } from '../../api/types';
import { formatNumber, formatPercent } from '../../ui/format';
import { isAblationFile } from '../../data';
import { dictionaries } from '../../i18n/dictionaries';
import { I18nProvider } from '../../i18n/I18nContext';
import { TimelineProvider } from '../../state/TimelineContext';
import { coverageOf, stateOf, toEntries } from './ablation';
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
    expect(view.container.querySelectorAll('.abl-table tbody tr')).toHaveLength(
      ablationFixture.rules.length
    )
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
    expect(zero.querySelector('.abl-flag')?.textContent).toBe(ru['npv.ablation.flag.on']);
    expect(disabled.textContent).toContain(
      ru['npv.ablation.disabledReason.UPLIFT_NOT_MEASURED']
    );
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

  it('draws the share bar from the artifact share without recomputing it', async () => {
    const { container } = await renderView();
    const bar = ruleRow(container, 'R0').querySelector('.abl-bar') as HTMLElement;
    expect(bar.style.getPropertyValue('--abl-bar-ratio')).toBe('0.3');
    expect(ruleRow(container, 'R2').querySelector('.abl-bar')).toBeNull();
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
    expect(line).toContain(
      ru['npv.ablation.coverageGap'].replace('{count}', String(unmeasured)).trim()
    );
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
