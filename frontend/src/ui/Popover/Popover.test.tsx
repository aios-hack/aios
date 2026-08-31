import { fireEvent, render, screen, waitForElementToBeRemoved } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Popover } from './Popover';

const LABEL = 'Легенда карты';

const renderPopover = () =>
  render(
    <div>
      <button type="button">снаружи</button>
      <Popover
        label={LABEL}
        trigger={({ ref, open, onClick }) => (
          <button
            ref={ref}
            type="button"
            aria-expanded={open}
            aria-haspopup="dialog"
            onClick={onClick}
          >
            открыть
          </button>
        )}
      >
        <p>содержимое панели</p>
      </Popover>
    </div>
  );

const openPanel = async () => {
  fireEvent.click(screen.getByRole('button', { name: 'открыть' }));
  return screen.findByRole('dialog', { name: LABEL });
};

describe('Popover', () => {
  it('keeps the panel out of the DOM until the trigger is used', () => {
    renderPopover();

    expect(screen.queryByRole('dialog')).toBeNull();
    expect(screen.getByRole('button', { name: 'открыть' }).getAttribute('aria-expanded')).toBe(
      'false'
    );
  });

  it('opens the labelled panel with its children on trigger click', async () => {
    renderPopover();

    const panel = await openPanel();

    expect(panel.textContent).toContain('содержимое панели');
    expect(screen.getByRole('button', { name: 'открыть' }).getAttribute('aria-expanded')).toBe(
      'true'
    );
    expect(screen.getByRole('button', { name: 'открыть' }).getAttribute('aria-haspopup')).toBe(
      'dialog'
    );
  });

  it('toggles back closed when the trigger is clicked again', async () => {
    renderPopover();
    await openPanel();

    fireEvent.click(screen.getByRole('button', { name: 'открыть' }));

    await waitForElementToBeRemoved(() => screen.queryByRole('dialog'));
    expect(screen.getByRole('button', { name: 'открыть' }).getAttribute('aria-expanded')).toBe(
      'false'
    );
  });

  it('closes on Escape and returns focus to the trigger', async () => {
    renderPopover();
    await openPanel();

    fireEvent.keyDown(window, { key: 'Escape' });

    await waitForElementToBeRemoved(() => screen.queryByRole('dialog'));
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'открыть' }));
  });

  it('closes when a pointer goes down outside the panel and the trigger', async () => {
    renderPopover();
    await openPanel();

    fireEvent.pointerDown(screen.getByRole('button', { name: 'снаружи' }));

    await waitForElementToBeRemoved(() => screen.queryByRole('dialog'));
  });

  it('stays open when the pointer goes down inside the panel', async () => {
    renderPopover();
    const panel = await openPanel();

    fireEvent.pointerDown(screen.getByText('содержимое панели'));

    expect(screen.getByRole('dialog', { name: LABEL })).toBe(panel);
  });

  it('marks the panel as closing before it leaves the DOM', async () => {
    renderPopover();
    const panel = await openPanel();

    expect(panel.dataset.closing).toBe('false');

    fireEvent.keyDown(window, { key: 'Escape' });

    expect(screen.getByRole('dialog', { name: LABEL }).dataset.closing).toBe('true');
    await waitForElementToBeRemoved(() => screen.queryByRole('dialog'));
  });

  it('ignores keys other than Escape', async () => {
    renderPopover();
    await openPanel();

    fireEvent.keyDown(window, { key: 'Enter' });

    expect(screen.getByRole('dialog', { name: LABEL })).not.toBeNull();
  });

  it('aligns to the end edge by default and honours an explicit alignment', async () => {
    const { unmount } = renderPopover();

    expect((await openPanel()).dataset.align).toBe('end');
    unmount();

    render(
      <Popover
        label={LABEL}
        align="start"
        trigger={({ ref, open, onClick }) => (
          <button ref={ref} type="button" aria-expanded={open} onClick={onClick}>
            открыть
          </button>
        )}
      >
        <p>содержимое панели</p>
      </Popover>
    );

    expect((await openPanel()).dataset.align).toBe('start');
  });
});
