import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useEffect, type ReactNode } from 'react';
import type { HierarchyFile, HierarchyStep, TimelineFile } from '../../api/types';
import { isHierarchyFile } from '../../data';
import { dictionaries } from '../../i18n/dictionaries';
import { I18nProvider } from '../../i18n/I18nContext';
import { TimelineProvider, useTimeline } from '../../state/TimelineContext';
import { Council } from './Council';
import { WellLevel } from './WellLevel';
import {
  fieldSegments,
  groupOrder,
  hasUngrouped,
  pathOf,
  stepAt,
  ungroupedWells,
  wellsOf
} from './levels';

const { ru } = dictionaries;

const GROUPS = ['G1', 'G2'];
const STEP_COUNT = 3;

const makeStep = (k: number): HierarchyStep => ({
  control_step: k,
  field: {
    injection_limit_m3_per_day: 1000 + 100 * k,
    water_available_m3_per_day: 1200 + 100 * k,
    allocations: [
      { group: 'G1', limit_m3_per_day: 600 + 100 * k },
      { group: 'G2', limit_m3_per_day: 400 }
    ]
  },
  groups: [
    {
      group: 'G1',
      received_m3_per_day: 600 + 100 * k,
      allocations: [
        { well: '1', value_m3_per_day: 300 + 50 * k },
        { well: '2', value_m3_per_day: 200 },
        { well: '3', value_m3_per_day: 100 }
      ]
    },
    {
      group: 'G2',
      received_m3_per_day: 400,
      allocations: [{ well: '4', value_m3_per_day: 400 }]
    }
  ],
  ungrouped: [{ well: '9', value_m3_per_day: 7 + k }],
  wells: [
    {
      well: '1',
      group: 'G1',
      decision: `SET_RATE ${300 + 50 * k}`,
      rule: 'R1',
      inputs: { group_limit_m3_per_day: 600 + 100 * k },
      constraint: null
    },
    {
      well: '2',
      group: 'G1',
      decision: 'SET_LRAT 200',
      rule: 'R2',
      inputs: { liquid_rate_m3_per_day: 200 },
      constraint: 'OUTAGE'
    },
    {
      well: '4',
      group: 'G2',
      decision: 'SET_RATE 400',
      rule: 'R1',
      inputs: { group_limit_m3_per_day: 400 },
      constraint: null
    },
    {
      well: '9',
      group: null,
      decision: 'SET_LRAT 7',
      rule: 'R2',
      inputs: { liquid_rate_m3_per_day: 7 },
      constraint: null
    }
  ]
});

const hierarchyFixture: HierarchyFile = {
  n_control_dates: STEP_COUNT,
  groups: GROUPS,
  ungrouped: ['9'],
  steps: Array.from({ length: STEP_COUNT }, (_, k) => makeStep(k))
};

const groupedOnlyFixture: HierarchyFile = {
  ...hierarchyFixture,
  ungrouped: [],
  steps: hierarchyFixture.steps.map((step) => ({
    ...step,
    ungrouped: [],
    wells: step.wells.filter((well) => well.group !== null)
  }))
};

const timelineFixture: TimelineFile = {
  model: 'Model_Z',
  t0: '2007-01-01',
  n_control_dates: STEP_COUNT,
  n_intervals: STEP_COUNT - 1,
  wells: ['1', '2', '4', '9'],
  steps: Array.from({ length: STEP_COUNT }, (_, k) => ({
    control_step: k,
    date: `${2007 + k}-01-01`,
    terminal: k === STEP_COUNT - 1,
    field: {
      production: 100,
      injection: 80,
      compensation: 0.8,
      npv_cumulative: 1000 * (k + 1),
      active_wells: 4
    },
    wells: ['1', '2', '4', '9'].map((well) => ({
      well,
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
    }))
  }))
};

let hierarchyPayload: HierarchyFile = hierarchyFixture;

const mockFetch = () => {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string) => {
      const payload = url.includes('hierarchy')
        ? hierarchyPayload
        : url.includes('timeline')
          ? timelineFixture
          : {};
      return Promise.resolve({ ok: true, json: () => Promise.resolve(payload) });
    })
  );
};

const Driver = ({ step, well }: { step: number; well: string | null }) => {
  const { timeline, setStepIndex, selectWell } = useTimeline();
  const ready = timeline.status === 'ready';
  useEffect(() => {
    if (!ready) {
      return;
    }
    setStepIndex(step);
    selectWell(well);
  }, [ready, step, well, setStepIndex, selectWell]);
  return null;
};

const withProviders = (node: ReactNode) => (
  <I18nProvider>
    <TimelineProvider>{node}</TimelineProvider>
  </I18nProvider>
);

const renderCouncil = async (step = 0, well: string | null = null) => {
  const view = render(
    withProviders(
      <>
        <Driver step={step} well={well} />
        <Council />
      </>
    )
  );
  await waitFor(() => expect(view.container.querySelector('.council')).not.toBeNull());
  return view;
};

beforeEach(() => {
  localStorage.clear();
  hierarchyPayload = hierarchyFixture;
  mockFetch();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('Council numbers follow the step', () => {
  it('changes numbers on at least two levels when stepIndex changes', async () => {
    const view = await renderCouncil(0);
    const fieldFirst = screen.getByTestId('council-field-limit').textContent;
    const groupFirst = screen.getByTestId('council-received-G1').textContent;
    const wellFirst = screen.getByTestId('council-well-1').textContent;

    view.rerender(
      withProviders(
        <>
          <Driver step={2} well={null} />
          <Council />
        </>
      )
    );
    await waitFor(() =>
      expect(screen.getByTestId('council-field-limit').textContent).not.toBe(fieldFirst)
    );
    expect(screen.getByTestId('council-received-G1').textContent).not.toBe(groupFirst);
    expect(screen.getByTestId('council-well-1').textContent).not.toBe(wellFirst);
  });

  it('derives field segment shares from the data without recomputing totals', () => {
    const order = groupOrder(hierarchyFixture);
    const step = stepAt(hierarchyFixture, 0);
    const segments = fieldSegments(step, order);
    expect(segments.map((s) => s.limit)).toEqual([600, 400]);
    expect(segments[0].share).toBeCloseTo(0.6);
    expect(segments[1].share).toBeCloseTo(0.4);
  });
});

describe('Council selection path', () => {
  it('highlights exactly one executor, one group and one field segment', async () => {
    const { container } = await renderCouncil(0, '1');
    await waitFor(() =>
      expect(screen.getByTestId('council-well-1').getAttribute('data-state')).toBe('path')
    );
    const onPath = (selector: string) =>
      [...container.querySelectorAll(`${selector}[data-state="path"]`)].length;
    expect(onPath('.council-column')).toBe(1);
    expect(onPath('.council-card')).toBe(1);
    expect(onPath('.council-table tbody tr')).toBe(1);
    expect(screen.getByTestId('council-segment-G1').getAttribute('data-state')).toBe(
      'path'
    );
    expect(screen.getByTestId('council-card-G1').getAttribute('data-state')).toBe('path');
    expect(screen.getByTestId('council-segment-G2').getAttribute('data-state')).toBe('dim');
  });

  it('marks groups that received nothing so they can shrink out of the way', async () => {
    const { container } = await renderCouncil(0, null);
    const cards = [...container.querySelectorAll('.council-card')];
    expect(cards.length).toBeGreaterThan(0);

    for (const card of cards) {
      const received = card.querySelector('.council-number')?.textContent?.trim();
      const empty = card.getAttribute('data-empty') === 'true';
      expect(empty).toBe(received === '0');
    }
  });

  it('names each group once: on the cap, never repeated in the card body', async () => {
    const { container } = await renderCouncil(0, null);
    const column = container.querySelector('.council-column') as HTMLElement;
    const caps = column.querySelectorAll('.council-cap-name');
    expect(caps).toHaveLength(1);
    expect(column.querySelectorAll('.council-card-name')).toHaveLength(0);
  });

  it('makes the whole column pick the group, not just the coloured cap', async () => {
    const { container } = await renderCouncil(0, null);
    const column = container.querySelector('.council-column') as HTMLElement;
    const pick = column.querySelector('.council-column-pick');
    expect(pick).not.toBeNull();
    expect(column.querySelector('.council-cap')?.tagName).toBe('SPAN');
  });

  it('labels the allocation total so no number floats without a name', async () => {
    const { container } = await renderCouncil(0, null);
    const total = container.querySelector('.council-column .council-card-total');
    expect(total?.querySelector('.council-card-total-label')).not.toBeNull();
    expect(container.querySelector('.council-card-listlabel')).not.toBeNull();
  });

  it('shows the water budget as labelled stats plus a usage meter, below the columns', async () => {
    const { container } = await renderCouncil(0, null);
    const stats = container.querySelectorAll('.council-budget-stat');
    expect(stats).toHaveLength(3);
    for (const stat of stats) {
      expect(stat.querySelector('.council-budget-label')).not.toBeNull();
    }
    const meter = container.querySelector('.council-budget-meter-fill') as HTMLElement;
    expect(meter.style.inlineSize).toMatch(/%$/);
    const budget = container.querySelector('.council-budget') as HTMLElement;
    const columns = container.querySelector('.council-groups') as HTMLElement;
    expect(columns.compareDocumentPosition(budget) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('gives both budget figures the same weight: neither is the odd one out', async () => {
    const { container } = await renderCouncil(0, null);
    const values = [...container.querySelectorAll('.council-budget-value')];
    expect(values).toHaveLength(2);
    expect(values.every((v) => v.className === values[0].className)).toBe(true);
  });

  it('rings the whole column, cap included, rather than the text panel alone', async () => {
    const css = readFileSync(
      join(process.cwd(), 'src', 'views', 'Council', 'CouncilField.css'),
      'utf-8'
    );
    expect(css).toMatch(/\.council-column\[data-open='true'\]\s*\{[^}]*outline:/);
    expect(css).toMatch(/\.council-column\[data-state='path'\]\s*\{[^}]*outline:/);
    const groups = readFileSync(
      join(process.cwd(), 'src', 'views', 'Council', 'CouncilGroups.css'),
      'utf-8'
    );
    expect(groups).not.toMatch(/\.council-card\[data-open='true'\]/);
  });

  it('dims the columns off the path, not a class that no longer renders', async () => {
    const css = readFileSync(
      join(process.cwd(), 'src', 'views', 'Council', 'Council.css'),
      'utf-8'
    );
    expect(css).toContain(".council-column[data-state='dim']");
    expect(css).not.toContain('.council-bar-segment');
  });

  it('titles both levels as plain phrases, with no separator punctuation', () => {
    for (const lang of ['ru', 'en'] as const) {
      const d = dictionaries[lang];
      expect(d['council.groups.title']).not.toMatch(/[·|]/);
      expect(d['council.wells.title']).not.toMatch(/[·|]/);
      expect(d['council.wells.title']).toContain('{group}');
      expect(d['council.wells.titleUngrouped']).not.toContain('{group}');
    }
  });

  it('reads naturally for wells that belong to no group', () => {
    render(
      <I18nProvider>
        <WellLevel rows={[]} groupLabel={null} path={null} onSelectWell={() => {}} />
      </I18nProvider>
    );
    const heading = screen.getByRole('heading', { level: 3 });
    expect(heading.textContent).toBe(ru['council.wells.titleUngrouped']);
    expect(heading.textContent).not.toContain('Вне участков');
  });

  it('pins the executor columns so they cannot resize as the step changes', () => {
    const css = readFileSync(
      join(process.cwd(), 'src', 'views', 'Council', 'CouncilWells.css'),
      'utf-8'
    );
    expect(css).toMatch(/\.council-table\s*\{[^}]*table-layout:\s*fixed/);
    const cols = [...css.matchAll(/\.council-col-[\w-]+\s*\{[^}]*width:\s*(\d+)px/g)];
    expect(cols.length).toBeGreaterThan(0);
  });

  it('starts every value at the same edge as its own header', () => {
    const css = readFileSync(
      join(process.cwd(), 'src', 'views', 'Council', 'CouncilWells.css'),
      'utf-8'
    );
    expect(css).toContain('.council-table td.council-cell-num');
    expect(css).toMatch(/td\.council-cell-num[^}]*text-align:\s*left/);
    expect(css).not.toMatch(/text-align:\s*right/);
  });

  it('gives every executor column its own sortable header', async () => {
    const { container } = await renderCouncil(0, null);
    const headers = [...container.querySelectorAll('.council-table thead th')].filter(
      (h) => h.querySelector('button') !== null
    );
    expect(headers).toHaveLength(8);
    for (const th of headers) {
      expect(th.getAttribute('aria-sort')).not.toBeNull();
    }
    expect(headers.filter((h) => h.getAttribute('aria-sort') !== 'none')).toHaveLength(1);
  });

  it('splits each input into its own cell instead of one run-on column', async () => {
    const { container } = await renderCouncil(0, null);
    const first = container.querySelector('.council-table tbody tr') as HTMLElement;
    expect(first.children).toHaveLength(9);
    expect(container.querySelector('.council-inputs')).toBeNull();
    expect(first.querySelectorAll('.council-cell-num')).toHaveLength(4);
  });

  it('reorders rows when a header is clicked and marks the direction', async () => {
    const { container } = await renderCouncil(0, null);
    const before = [...container.querySelectorAll('.council-table tbody tr')].map(
      (r) => r.getAttribute('data-testid')
    );
    const amount = container.querySelectorAll('.council-table thead th')[2];
    fireEvent.click(amount.querySelector('button') as HTMLElement);
    expect(amount.getAttribute('aria-sort')).toBe('ascending');
    const after = [...container.querySelectorAll('.council-table tbody tr')].map(
      (r) => r.getAttribute('data-testid')
    );
    expect(after).not.toEqual(before);
    expect([...after].sort()).toEqual([...before].sort());
  });

  it('opens the well from any cell in the row, not just the number', async () => {
    const { container } = await renderCouncil(0, null);
    const row = container.querySelector('.council-table tbody tr') as HTMLElement;
    const lastCell = row.children[row.children.length - 2] as HTMLElement;
    expect(lastCell.querySelector('button')).toBeNull();
    fireEvent.click(lastCell);
    await waitFor(() =>
      expect(row.getAttribute('data-selected')).toBe('true')
    );
  });

  it('clears the time axis so the last rows are reachable', () => {
    const css = readFileSync(
      join(process.cwd(), 'src', 'views', 'Council', 'Council.css'),
      'utf-8'
    );
    const block = css.match(/\.council\s*\{[^}]*\}/)?.[0] ?? '';
    expect(block).toMatch(/padding-bottom:\s*var\(--h-axis-space/);
    expect(block).not.toMatch(/padding-bottom:\s*\d+px/);
  });

  it('keeps the eight columns legible by scrolling instead of crushing them', () => {
    const css = readFileSync(
      join(process.cwd(), 'src', 'views', 'Council', 'CouncilWells.css'),
      'utf-8'
    );
    expect(css).toMatch(/\.council-table-wrap\s*\{[^}]*overflow-x:\s*auto/);
    expect(css).toContain('min-width: var(--size-table-wide-min)');
    const theme = readFileSync(join(process.cwd(), 'src', 'theme', 'tokens.light.css'), 'utf-8');
    expect(theme).toMatch(/--size-table-wide-min:\s*\d+px/);
  });

  it('carries the group colour on a variable rather than a border stripe', async () => {
    const { container } = await renderCouncil(0, null);
    const card = container.querySelector('.council-card') as HTMLElement;
    expect(card.style.getPropertyValue('--council-card-accent')).not.toBe('');
    expect(card.style.borderTopColor).toBe('');
  });

  it('leaves everything undimmed when no well is selected', async () => {
    const { container } = await renderCouncil(0, null);
    expect(container.querySelectorAll('[data-state="dim"]')).toHaveLength(0);
    expect(container.querySelectorAll('[data-state="path"]')).toHaveLength(0);
  });

  it('selects a well from a group allocation list', async () => {
    const { container } = await renderCouncil(0, null);
    fireEvent.click(screen.getByTestId('council-alloc-2'));
    await waitFor(() =>
      expect(screen.getByTestId('council-well-2').getAttribute('data-state')).toBe('path')
    );
    expect(container.querySelectorAll('.council-card[data-state="path"]')).toHaveLength(1);
  });

  it('shows the physical constraint when it triggered and states absence otherwise', async () => {
    await renderCouncil(0, null);
    expect(screen.getByTestId('council-constraint-2').textContent).toBe(
      ru['council.constraint.OUTAGE']
    );
    expect(screen.getAllByText(ru['council.wells.noConstraint']).length).toBeGreaterThan(0);
  });
});

describe('Council ungrouped wells', () => {
  it('renders an explicit outside-groups row and its executors', async () => {
    await renderCouncil(0, '9');
    expect(screen.getByTestId('council-card-ungrouped')).toBeTruthy();
    expect(screen.getAllByText(ru['council.groups.ungrouped']).length).toBeGreaterThan(0);
    await waitFor(() =>
      expect(screen.getByTestId('council-well-9').getAttribute('data-state')).toBe('path')
    );
    expect(ungroupedWells(stepAt(hierarchyFixture, 0)).map((w) => w.well)).toEqual(['9']);
    expect(pathOf(stepAt(hierarchyFixture, 0), '9')).toEqual({ well: '9', group: null });
  });

  it('hides the outside-groups card when every well has a group', async () => {
    hierarchyPayload = groupedOnlyFixture;
    await renderCouncil(0, null);
    expect(screen.queryByTestId('council-card-ungrouped')).toBeNull();
    expect(hasUngrouped(groupedOnlyFixture, stepAt(groupedOnlyFixture, 0))).toBe(false);
  });

  it('lists ungrouped executors through wellsOf', () => {
    const order = groupOrder(hierarchyFixture);
    const rows = wellsOf(stepAt(hierarchyFixture, 0), null, order);
    expect(rows.map((row) => row.well)).toEqual(['9']);
    expect(rows[0].color).toBeNull();
  });
});

describe('hierarchy validator', () => {
  it('accepts the fixture and rejects broken payloads', () => {
    expect(isHierarchyFile(hierarchyFixture)).toBe(true);
    expect(isHierarchyFile({ ...hierarchyFixture, steps: [] })).toBe(false);
    expect(isHierarchyFile({ ...hierarchyFixture, groups: [1] })).toBe(false);
    expect(
      isHierarchyFile({
        ...hierarchyFixture,
        steps: [{ ...hierarchyFixture.steps[0], field: {} }]
      })
    ).toBe(false);
    expect(
      isHierarchyFile({
        ...hierarchyFixture,
        steps: [
          {
            ...hierarchyFixture.steps[0],
            wells: [{ ...hierarchyFixture.steps[0].wells[0], inputs: { a: 'x' } }]
          }
        ]
      })
    ).toBe(false);
  });
});
