import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { dictionaries } from '../../i18n/dictionaries';
import { YEAR_SECTIONS } from './constraints';
import { ConstraintsEditor } from './ConstraintsEditor';
import { flushProviders, mockFetch, withProviders } from './testFixtures';

const { ru } = dictionaries;

const addRow = (section: string) => {
  const block = document.querySelector(`[data-section="${section}"]`) as HTMLElement;
  fireEvent.click(within(block).getAllByRole('button', { name: /Добавить/ })[0]);
  return block;
};

const previewDoc = (): Record<string, unknown> =>
  JSON.parse(screen.getByTestId('constraints-preview').textContent ?? '{}');

const fillRow = (block: HTMLElement, values: string[]) => {
  const inputs = within(block).getAllByRole('textbox');
  values.forEach((value, index) =>
    fireEvent.change(inputs[index], { target: { value } })
  );
};

beforeEach(() => {
  localStorage.clear();
  mockFetch();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('ConstraintsEditor', () => {
  it('produces an empty but complete document before any edits', async () => {
    render(withProviders(<ConstraintsEditor nIntervals={224} />));
    await flushProviders();
    expect(previewDoc()).toEqual({
      injection_limits: {},
      liquid_limits: {},
      production_floors: {},
      watercut_limits: {},
      well_outages: [],
      infrastructure: {}
    });
  });

  it('builds a serializable document from edited rows', async () => {
    render(withProviders(<ConstraintsEditor nIntervals={224} />));
    await flushProviders();
    fillRow(addRow('injection_limits'), ['2007', '5000']);
    fillRow(addRow('well_outages'), ['42', '3', '7']);

    expect(previewDoc()).toMatchObject({
      injection_limits: { '2007': 5000 },
      well_outages: [{ well: '42', control_step_from: 3, control_step_to: 7 }]
    });
  });

  it('keeps free key-value infrastructure pairs in the document', async () => {
    render(withProviders(<ConstraintsEditor nIntervals={224} />));
    await flushProviders();
    fillRow(addRow('infrastructure'), ['kns_limit_m3_per_day', '12000']);
    expect(previewDoc()).toMatchObject({
      infrastructure: { kns_limit_m3_per_day: 12000 }
    });
  });

  it('shows an error when watercut is entered as a percentage', async () => {
    render(withProviders(<ConstraintsEditor nIntervals={224} />));
    await flushProviders();
    fillRow(addRow('watercut_limits'), ['2008', '50']);

    expect(screen.getByText(ru['scenarios.error.watercut'])).toBeTruthy();
    expect(
      (screen.getByRole('button', { name: ru['scenarios.action.download'] }) as HTMLButtonElement)
        .disabled
    ).toBe(true);
  });

  it('accepts a watercut fraction without complaint', async () => {
    render(withProviders(<ConstraintsEditor nIntervals={224} />));
    await flushProviders();
    fillRow(addRow('watercut_limits'), ['2008', '0.95']);

    expect(screen.queryByText(ru['scenarios.error.watercut'])).toBeNull();
    expect(previewDoc()).toMatchObject({ watercut_limits: { '2008': 0.95 } });
  });

  it('shows an error on a negative limit', async () => {
    render(withProviders(<ConstraintsEditor nIntervals={224} />));
    await flushProviders();
    fillRow(addRow('liquid_limits'), ['2007', '-1']);
    expect(screen.getByText(ru['scenarios.error.negative'])).toBeTruthy();
  });

  it('shows an error when an outage runs past the horizon', async () => {
    render(withProviders(<ConstraintsEditor nIntervals={4} />));
    await flushProviders();
    fillRow(addRow('well_outages'), ['42', '0', '9']);
    expect(
      screen.getByText(ru['scenarios.error.horizon'].replace('{last}', '3'))
    ).toBeTruthy();
  });

  it('shows an error when the outage range is reversed', async () => {
    render(withProviders(<ConstraintsEditor nIntervals={224} />));
    await flushProviders();
    fillRow(addRow('well_outages'), ['42', '7', '3']);
    expect(screen.getByText(ru['scenarios.error.range'])).toBeTruthy();
  });

  it('removes a row when the remove button is clicked', async () => {
    render(withProviders(<ConstraintsEditor nIntervals={224} />));
    await flushProviders();
    const block = addRow('injection_limits');
    fillRow(block, ['2007', '5000']);
    expect(previewDoc()).toMatchObject({ injection_limits: { '2007': 5000 } });

    fireEvent.click(
      within(block).getByRole('button', { name: ru['scenarios.action.removeRow'] })
    );
    expect(previewDoc()).toMatchObject({ injection_limits: {} });
  });
});

describe('ConstraintsEditor section layout', () => {
  it('lays every constraint section out in one shared grid so they wrap side by side', async () => {
    render(withProviders(<ConstraintsEditor nIntervals={224} />));
    await flushProviders();

    const grid = document.querySelector('.scenarios-grid');
    expect(grid).not.toBeNull();

    const sections = [...document.querySelectorAll('.scenarios-section')];
    expect(sections.length).toBe(YEAR_SECTIONS.length + 2);
    for (const section of sections) {
      expect(section.parentElement).toBe(grid);
    }
  });

  it('gives each section a distinct stagger index so the reveal is ordered, not simultaneous', async () => {
    render(withProviders(<ConstraintsEditor nIntervals={224} />));
    await flushProviders();

    const indices = [...document.querySelectorAll('.scenarios-section')].map((section) =>
      (section as HTMLElement).style.getPropertyValue('--scenarios-section-index')
    );

    expect(indices.every((value) => value !== '')).toBe(true);
    expect(indices).toEqual([...indices].sort((a, b) => Number(a) - Number(b)));
    expect(new Set(indices).size).toBe(indices.length);
  });

  it('keeps editing working through the grid wrapper', async () => {
    render(withProviders(<ConstraintsEditor nIntervals={224} />));
    await flushProviders();
    fillRow(addRow('liquid_limits'), ['2009', '7000']);
    expect(previewDoc()).toMatchObject({ liquid_limits: { '2009': 7000 } });
  });
});

describe('ConstraintsEditor JSON upload', () => {
  const upload = (content: string, name = 'constraints.json') => {
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File([content], name, { type: 'application/json' });
    Object.defineProperty(file, 'text', { value: () => Promise.resolve(content) });
    fireEvent.change(input, { target: { files: [file] } });
  };

  it('fills the form from a loaded document', async () => {
    render(withProviders(<ConstraintsEditor nIntervals={224} />));
    upload(
      JSON.stringify({
        injection_limits: { '2007': 5000 },
        watercut_limits: { '2008': 0.95 },
        well_outages: [{ well: '42', control_step_from: 1, control_step_to: 2 }],
        infrastructure: { kns: 12000 }
      })
    );

    await waitFor(() => expect(screen.getByDisplayValue('5000')).toBeTruthy());
    expect(screen.getByDisplayValue('0.95')).toBeTruthy();
    expect(screen.getByDisplayValue('42')).toBeTruthy();
    expect(screen.getByDisplayValue('kns')).toBeTruthy();
    expect(previewDoc()).toMatchObject({
      injection_limits: { '2007': 5000 },
      watercut_limits: { '2008': 0.95 },
      well_outages: [{ well: '42', control_step_from: 1, control_step_to: 2 }],
      infrastructure: { kns: 12000 }
    });
  });

  it('reports a percentage watercut in a loaded document instead of accepting it', async () => {
    render(withProviders(<ConstraintsEditor nIntervals={224} />));
    upload(JSON.stringify({ watercut_limits: { '2008': 50 } }));

    await screen.findByText(
      ru['scenarios.load.error.watercut'].replace('{year}', '2008').replace('{value}', '50')
    );
    expect(previewDoc()).toMatchObject({ watercut_limits: {} });
  });

  it('reports an outage past the horizon in a loaded document', async () => {
    render(withProviders(<ConstraintsEditor nIntervals={4} />));
    upload(
      JSON.stringify({
        well_outages: [{ well: '42', control_step_from: 0, control_step_to: 9 }]
      })
    );
    await screen.findByText(
      ru['scenarios.load.error.outageHorizon']
        .replace('{index}', '0')
        .replace('{last}', '3')
    );
  });

  it('reports malformed JSON', async () => {
    render(withProviders(<ConstraintsEditor nIntervals={224} />));
    upload('{ not json');
    await screen.findByText(ru['scenarios.load.error.json']);
  });

  it('reports an unknown section rather than dropping it silently', async () => {
    render(withProviders(<ConstraintsEditor nIntervals={224} />));
    upload(JSON.stringify({ bhp_limits: { '2007': 50 } }));
    await screen.findByText(
      ru['scenarios.load.error.unknownSection'].replace('{sections}', 'bhp_limits')
    );
  });
});
