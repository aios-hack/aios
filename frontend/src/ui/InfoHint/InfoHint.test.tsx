import {
  act,
  fireEvent,
  render,
  screen,
  waitForElementToBeRemoved
} from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { InfoHint } from './InfoHint';

const LABEL = 'Что такое NPV';
const TEXT = 'Чистая приведённая стоимость по методике заказчика';

const trigger = () => screen.getByRole('button', { name: LABEL });

describe('InfoHint', () => {
  it('renders a labelled trigger with no bubble at rest', () => {
    render(<InfoHint text={TEXT} label={LABEL} />);

    expect(trigger().getAttribute('aria-expanded')).toBe('false');
    expect(screen.queryByRole('tooltip')).toBeNull();
  });

  it('shows the hint text on click', () => {
    render(<InfoHint text={TEXT} label={LABEL} />);

    fireEvent.click(trigger());

    expect(screen.getByRole('tooltip').textContent).toBe(TEXT);
    expect(trigger().getAttribute('aria-expanded')).toBe('true');
  });

  it('hides the hint again on a second click', () => {
    render(<InfoHint text={TEXT} label={LABEL} />);

    fireEvent.click(trigger());
    fireEvent.click(trigger());

    expect(screen.queryByRole('tooltip')).toBeNull();
    expect(trigger().getAttribute('aria-expanded')).toBe('false');
  });

  it('shows the hint on hover and hides it once the pointer has left', async () => {
    render(<InfoHint text={TEXT} label={LABEL} />);

    fireEvent.mouseEnter(trigger());
    expect(screen.getByRole('tooltip').textContent).toBe(TEXT);

    fireEvent.mouseLeave(trigger());
    await waitForElementToBeRemoved(() => screen.queryByRole('tooltip'));
  });

  it('keeps the hint open while the pointer moves onto the bubble', async () => {
    render(<InfoHint text={TEXT} label={LABEL} />);

    fireEvent.mouseEnter(trigger());
    fireEvent.mouseLeave(trigger());
    fireEvent.mouseEnter(screen.getByRole('tooltip'));

    await new Promise((resolve) => setTimeout(resolve, 200));

    expect(screen.getByRole('tooltip').textContent).toBe(TEXT);

    fireEvent.mouseLeave(screen.getByRole('tooltip'));
    await waitForElementToBeRemoved(() => screen.queryByRole('tooltip'));
  });

  it('dismisses the hint on Escape and returns focus to the trigger', () => {
    render(<InfoHint text={TEXT} label={LABEL} />);

    fireEvent.focus(trigger());
    expect(screen.getByRole('tooltip').textContent).toBe(TEXT);

    fireEvent.keyDown(document, { key: 'Escape' });

    expect(screen.queryByRole('tooltip')).toBeNull();
    expect(document.activeElement).toBe(trigger());
  });

  it('opens on keyboard focus, so the hint is not mouse-only', () => {
    render(<InfoHint text={TEXT} label={LABEL} />);

    fireEvent.focus(trigger());

    expect(screen.getByRole('tooltip').textContent).toBe(TEXT);
  });

  it('closes when focus leaves the trigger', () => {
    render(<InfoHint text={TEXT} label={LABEL} />);

    fireEvent.focus(trigger());
    fireEvent.blur(trigger());

    expect(screen.queryByRole('tooltip')).toBeNull();
  });

  it('is reachable with the keyboard as a real button', () => {
    render(<InfoHint text={TEXT} label={LABEL} />);

    expect(trigger().tagName).toBe('BUTTON');
    expect(trigger().getAttribute('type')).toBe('button');
    act(() => trigger().focus());
    expect(document.activeElement).toBe(trigger());
  });

  it('describes the trigger by the bubble only while it is open', () => {
    render(<InfoHint text={TEXT} label={LABEL} />);

    expect(trigger().getAttribute('aria-describedby')).toBeNull();

    fireEvent.click(trigger());

    const described = trigger().getAttribute('aria-describedby');
    expect(described).not.toBeNull();
    expect(screen.getByRole('tooltip').id).toBe(described);
  });

  it('renders the bubble into the document body, outside the trigger wrapper', () => {
    const { container } = render(<InfoHint text={TEXT} label={LABEL} />);

    fireEvent.click(trigger());

    const bubble = screen.getByRole('tooltip');
    expect(container.contains(bubble)).toBe(false);
    expect(document.body.contains(bubble)).toBe(true);
  });

  it('keeps the bubble inside the viewport edges', () => {
    render(<InfoHint text={TEXT} label={LABEL} />);

    fireEvent.click(trigger());

    const left = Number.parseFloat(screen.getByRole('tooltip').style.left);
    expect(left).toBeGreaterThanOrEqual(0);
    expect(left).toBeLessThanOrEqual(window.innerWidth);
  });

  it('keeps a second hint independent of the first', () => {
    render(
      <div>
        <InfoHint text={TEXT} label={LABEL} />
        <InfoHint text="Другая подсказка" label="Что такое компенсация" />
      </div>
    );

    fireEvent.click(screen.getByRole('button', { name: 'Что такое компенсация' }));

    expect(screen.getAllByRole('tooltip')).toHaveLength(1);
    expect(screen.getByRole('tooltip').textContent).toBe('Другая подсказка');
    expect(trigger().getAttribute('aria-expanded')).toBe('false');
  });
});
