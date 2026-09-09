import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import type { AblationFile } from '../../api/types';
import { isAblationFile } from '../../data';
import { dictionaries } from '../../i18n/dictionaries';
import { I18nProvider } from '../../i18n/I18nContext';
import { TimelineProvider } from '../../state/TimelineContext';
import { Rules } from './Rules';

const { ru } = dictionaries;

const shipped = JSON.parse(
  readFileSync(join(process.cwd(), 'public', 'data', 'ablation.json'), 'utf-8')
) as unknown;

const measuredFixture: AblationFile = {
  npv_total: 1000,
  rules: [
    { rule: 'R0', enabled: true, delta_npv: 300, share: 0.3 },
    { rule: 'R7', enabled: false, delta_npv: null, share: null }
  ]
};

const withProviders = (node: ReactNode) => (
  <I18nProvider>
    <TimelineProvider>{node}</TimelineProvider>
  </I18nProvider>
);

const mockFetch = (payload: unknown) => {
  vi.stubGlobal(
    'fetch',
    vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve(payload) }))
  );
};

const renderRules = async (payload: unknown) => {
  mockFetch(payload);
  const result = render(withProviders(<Rules />));
  await waitFor(() => expect(document.querySelector('.abl-table')).not.toBeNull());
  return result;
};

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('Rules view over the shipped artifact', () => {
  it('accepts the shipped artifact', () => {
    expect(isAblationFile(shipped)).toBe(true);
  });

  it('says the contribution is not measured instead of showing money', async () => {
    await renderRules(shipped);
    const notice = screen.getByTestId('rules-not-measured');
    expect(notice.textContent).toContain(ru['npv.ablation.notRun.title']);
    expect(notice.textContent).toContain(ru['npv.ablation.notRun.body']);
  });

  it('shows "not measured" in every contribution cell', async () => {
    const { container } = await renderRules(shipped);
    const cells = container.querySelectorAll('tbody .abl-cell-delta');
    expect(cells.length).toBeGreaterThan(0);
    for (const cell of cells) {
      expect(cell.textContent).toContain(ru['npv.ablation.unmeasured']);
    }
  });

  it('renders neither a zero nor a dash in place of the contribution', async () => {
    const { container } = await renderRules(shipped);
    for (const cell of container.querySelectorAll('tbody .abl-cell-delta')) {
      expect(cell.textContent).not.toContain(ru['npv.ablation.zero']);
      expect(cell.textContent).not.toContain('—');
      expect(cell.querySelector('.abl-zero')).toBeNull();
      expect(cell.querySelector('.abl-delta')).toBeNull();
    }
  });

  it('still reports which rules were enabled and which were switched off', async () => {
    const { container } = await renderRules(shipped);
    const disabled = container.querySelector('tr[data-rule-id="R7"]');
    expect(disabled?.getAttribute('data-state')).toBe('disabled');
    expect(disabled?.querySelector('.abl-flag')?.textContent).toBe(
      ru['npv.ablation.flag.off']
    );
    const enabled = container.querySelector('tr[data-rule-id="R0"]');
    expect(enabled?.getAttribute('data-state')).toBe('unmeasured');
    expect(enabled?.querySelector('.abl-flag')).toBeNull();
  });

  it('keeps the notice off once a real measurement exists', async () => {
    await renderRules(measuredFixture);
    expect(screen.queryByTestId('rules-not-measured')).toBeNull();
  });
});
