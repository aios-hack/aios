import { render, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import type { HierarchyFile } from '@/entities/hierarchy/types';
import type { TimelineFile } from '@/entities/timeline/types';
import { isHierarchyFile } from '@/entities';
import { I18nProvider } from '@/shared/i18n/I18nContext';
import { TimelineProvider } from '@/entities/timeline/model/TimelineContext';
import { Council } from '@/pages/council/ui/Council/Council';
import ruShowcase from '@/shared/i18n/locales/ru/showcase.json';
import enShowcase from '@/shared/i18n/locales/en/showcase.json';

const STEP_COUNT = 2;

const hierarchyFixture = (meta?: HierarchyFile['meta']): HierarchyFile => ({
  ...(meta === undefined ? {} : { meta }),
  n_control_dates: STEP_COUNT,
  groups: ['G1'],
  ungrouped: [],
  steps: Array.from({ length: STEP_COUNT }, (_, k) => ({
    control_step: k,
    field: {
      injection_limit_m3_per_day: 1000,
      water_available_m3_per_day: 1200,
      allocations: [{ group: 'G1', limit_m3_per_day: 1000 }]
    },
    groups: [
      {
        group: 'G1',
        received_m3_per_day: 1000,
        allocations: [{ well: '1', value_m3_per_day: 1000 }]
      }
    ],
    ungrouped: [],
    wells: [
      {
        well: '1',
        group: 'G1',
        decision: 'SET_RATE 1000',
        rule: 'R1',
        inputs: { group_limit_m3_per_day: 1000 },
        constraint: null
      }
    ]
  }))
});

const timelineFixture: TimelineFile = {
  model: 'Model_Z',
  t0: '2007-01-01',
  n_control_dates: STEP_COUNT,
  n_intervals: STEP_COUNT - 1,
  wells: ['1'],
  steps: Array.from({ length: STEP_COUNT }, (_, k) => ({
    control_step: k,
    date: `${2007 + k}-01-01`,
    terminal: k === STEP_COUNT - 1,
    field: {
      production: 100,
      injection: 80,
      compensation: 0.8,
      npv_cumulative: 1000,
      active_wells: 1
    },
    wells: [
      {
        well: '1',
        availability: 'AVAILABLE' as const,
        role: 'PROD' as const,
        operating_status: 'OPEN' as const,
        setpoint: 50,
        liquid_rate: 40,
        injection_rate: 0,
        bhp: 90,
        watercut: 0.5,
        fact_to_target: 0.8,
        cumulative_liquid: 100
      }
    ]
  }))
};

let hierarchyPayload: HierarchyFile = hierarchyFixture();

const withProviders = (node: ReactNode) => (
  <I18nProvider>
    <TimelineProvider>{node}</TimelineProvider>
  </I18nProvider>
);

const renderCouncil = async () => {
  const view = render(withProviders(<Council />));
  await waitFor(() => expect(view.container.querySelector('.council')).not.toBeNull());
  return view;
};

beforeEach(() => {
  localStorage.clear();
  hierarchyPayload = hierarchyFixture();
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string) => {
      const stepMatch = /hierarchy[/](\d+)[.]json/.exec(url);
      const payload = stepMatch !== null
        ? hierarchyPayload.steps[Number(stepMatch[1])]
        : url.includes('hierarchy-index')
          ? {
              ...hierarchyPayload,
              steps: undefined,
              step_count: hierarchyPayload.steps.length,
              step_path: 'hierarchy/{step}.json'
            }
          : url.includes('timeline')
            ? timelineFixture
            : {};
      return Promise.resolve({ ok: true, json: () => Promise.resolve(payload) });
    })
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('council states where its data came from', () => {
  it('stays silent when the run data is real', async () => {
    hierarchyPayload = hierarchyFixture({
      kind: 'hierarchy',
      provenance: 'policy-hierarchy-trace',
      synthetic: false
    });
    const view = await renderCouncil();
    expect(view.queryByTestId('council-synthetic')).toBeNull();
  });

  it('stays silent when the artifact carries no meta at all', async () => {
    hierarchyPayload = hierarchyFixture();
    const view = await renderCouncil();
    expect(view.queryByTestId('council-synthetic')).toBeNull();
  });

  it('warns loudly when the council is drawn from synthetic data', async () => {
    hierarchyPayload = hierarchyFixture({
      kind: 'hierarchy',
      provenance: 'synthetic-demo',
      synthetic: true
    });
    const view = await renderCouncil();
    const notice = view.getByTestId('council-synthetic');
    expect(notice.textContent).toContain('Демонстрационные данные');
    expect(notice.textContent).toContain('не результат расчёта');
  });

  it('names the provenance of the synthetic data', async () => {
    hierarchyPayload = hierarchyFixture({
      kind: 'hierarchy',
      provenance: 'synthetic-demo',
      synthetic: true
    });
    const view = await renderCouncil();
    expect(view.getByTestId('council-synthetic').textContent).toContain('synthetic-demo');
  });

  it('keeps accepting a hierarchy file that declares synthetic in meta', () => {
    expect(
      isHierarchyFile(
        hierarchyFixture({
          kind: 'hierarchy',
          provenance: 'synthetic-demo',
          synthetic: true
        })
      )
    ).toBe(true);
  });

  it('keeps accepting a hierarchy file with no synthetic flag', () => {
    expect(isHierarchyFile(hierarchyFixture())).toBe(true);
  });
});

describe('council states which showcase notice the artifact carries', () => {
  it('says nothing when the artifact carries no notice', async () => {
    hierarchyPayload = hierarchyFixture({ kind: 'hierarchy', provenance: 'policy-hierarchy-trace' });
    const view = await renderCouncil();
    expect(view.queryByTestId('council-source')).toBeNull();
  });

  it('renders the catalog text for a notice key rather than the served string', async () => {
    hierarchyPayload = hierarchyFixture({
      kind: 'hierarchy',
      provenance: 'policy-hierarchy-trace',
      notice: 'a stale string the exporter baked in',
      notice_key: 'showcase.notice.hierarchy'
    });
    const view = await renderCouncil();
    expect(view.getByTestId('council-source').textContent).toBe(
      ruShowcase['notice.hierarchy']
    );
  });

  it('follows the console language without reloading the artifact', async () => {
    localStorage.setItem('aios-lang', 'en');
    hierarchyPayload = hierarchyFixture({
      kind: 'hierarchy',
      provenance: 'policy-hierarchy-trace',
      notice: 'a stale string the exporter baked in',
      notice_key: 'showcase.notice.hierarchy'
    });
    const view = await renderCouncil();
    expect(view.getByTestId('council-source').textContent).toBe(
      enShowcase['notice.hierarchy']
    );
  });

  it('falls back to the served string when the key is not in the catalog', async () => {
    hierarchyPayload = hierarchyFixture({
      kind: 'hierarchy',
      provenance: 'policy-hierarchy-trace',
      notice: 'a notice only the exporter knows',
      notice_key: 'showcase.notice.invented_by_a_newer_backend'
    });
    const view = await renderCouncil();
    expect(view.getByTestId('council-source').textContent).toBe(
      'a notice only the exporter knows'
    );
  });
});
