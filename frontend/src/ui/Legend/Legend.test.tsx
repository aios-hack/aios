import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Legend, type LegendNote, type LegendRamp, type LegendSwatch } from './Legend';
import { LegendPopover } from './LegendPopover';

const TITLE = 'Условные обозначения';

const NOTES: LegendNote[] = [
  { text: 'Размер круга — накопленная добыча', testId: 'legend-note-size' },
  { text: 'Пунктир — прогноз' }
];

const SWATCHES: LegendSwatch[] = [
  { key: 'prod', color: 'var(--color-graph-producer)', label: 'Добывающая' },
  { key: 'inj', color: 'var(--color-graph-injector)', label: 'Нагнетательная' }
];

const RAMP: LegendRamp = {
  colorAt: (stop) => `rgba(0, 0, 0, ${stop})`,
  lowLabel: '0 м³',
  highLabel: '500 м³'
};

describe('Legend', () => {
  it('is reachable as a group named by its title', () => {
    render(<Legend title={TITLE} notes={NOTES} />);

    expect(screen.getByRole('group', { name: TITLE })).not.toBeNull();
  });

  it('shows the title as visible text, not only as a label', () => {
    render(<Legend title={TITLE} notes={NOTES} />);

    expect(screen.getByText(TITLE)).not.toBeNull();
  });

  it('renders every note with its text visible', () => {
    render(<Legend title={TITLE} notes={NOTES} />);

    for (const note of NOTES) {
      expect(screen.getByText(note.text)).not.toBeNull();
    }
  });

  it('carries the test id through to the note that asked for one', () => {
    render(<Legend title={TITLE} notes={NOTES} />);

    expect(screen.getByTestId('legend-note-size').textContent).toBe(NOTES[0].text);
  });

  it('renders no notes when none were given', () => {
    const { container } = render(<Legend title={TITLE} />);

    expect(container.querySelectorAll('.legend-note')).toHaveLength(0);
  });

  it('lists swatches with their labels', () => {
    render(<Legend title={TITLE} swatches={SWATCHES} />);

    const items = screen.getAllByRole('listitem');
    expect(items.map((item) => item.textContent)).toEqual([
      'Добывающая',
      'Нагнетательная'
    ]);
  });

  it('hides the decorative swatch chips from assistive tech', () => {
    const { container } = render(<Legend title={TITLE} swatches={SWATCHES} />);

    const chips = [...container.querySelectorAll('.legend-swatch')];
    expect(chips).toHaveLength(2);
    expect(chips.every((chip) => chip.getAttribute('aria-hidden') === 'true')).toBe(true);
  });

  it('omits the swatch list when the array is empty', () => {
    const { container } = render(<Legend title={TITLE} swatches={[]} />);

    expect(container.querySelector('.legend-list')).toBeNull();
  });

  it('shows both ends of a ramp scale as text', () => {
    render(<Legend title={TITLE} ramp={RAMP} />);

    expect(screen.getByText(RAMP.lowLabel)).not.toBeNull();
    expect(screen.getByText(RAMP.highLabel)).not.toBeNull();
  });
});

describe('LegendPopover', () => {
  it('renders only the labelled trigger until it is opened', () => {
    render(<LegendPopover title={TITLE} triggerLabel="Показать легенду" notes={NOTES} />);

    expect(screen.getByRole('button', { name: 'Показать легенду' })).not.toBeNull();
    expect(screen.queryByRole('group', { name: TITLE })).toBeNull();
  });

  it('reveals the legend and its notes inside a dialog named by the title', async () => {
    render(<LegendPopover title={TITLE} triggerLabel="Показать легенду" notes={NOTES} />);

    fireEvent.click(screen.getByRole('button', { name: 'Показать легенду' }));

    const dialog = await screen.findByRole('dialog', { name: TITLE });
    expect(dialog.contains(screen.getByRole('group', { name: TITLE }))).toBe(true);
    for (const note of NOTES) {
      expect(screen.getByText(note.text)).not.toBeNull();
    }
  });

  it('reports the open state on the trigger', async () => {
    render(<LegendPopover title={TITLE} triggerLabel="Показать легенду" notes={NOTES} />);
    const trigger = screen.getByRole('button', { name: 'Показать легенду' });

    expect(trigger.getAttribute('aria-expanded')).toBe('false');

    fireEvent.click(trigger);
    await screen.findByRole('dialog', { name: TITLE });

    expect(trigger.getAttribute('aria-expanded')).toBe('true');
  });
});
