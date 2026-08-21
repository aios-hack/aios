import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { DemoScriptFile } from '../../api/types';
import { dictionaries } from '../../i18n/dictionaries';
import { I18nProvider } from '../../i18n/I18nContext';
import { ConsoleProvider } from '../../state/ConsoleContext';
import { ScenarioProvider } from '../../state/ScenarioContext';
import { TimelineProvider, useTimeline } from '../../state/TimelineContext';
import { ThemeProvider } from '../../theme/ThemeContext';
import { DemoControls } from './DemoControls';
import { DemoProvider, DemoStage, useDemo } from './DemoMode';
import { scriptFixture, timelineFixture, traceFixture } from './fixtures';

const { ru } = dictionaries;

const mockFetch = (script: DemoScriptFile = scriptFixture) => {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string) => {
      const payload = url.includes('demo-script')
        ? script
        : url.includes('timeline')
          ? timelineFixture
          : url.includes('trace')
            ? traceFixture
            : {};
      return Promise.resolve({ ok: true, json: () => Promise.resolve(payload) });
    })
  );
};

const matchMedia = (reduced: boolean) =>
  vi.stubGlobal(
    'matchMedia',
    vi.fn((query: string) => ({
      matches: reduced && query.includes('prefers-reduced-motion'),
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      onchange: null,
      dispatchEvent: vi.fn()
    }))
  );

const Probe = () => {
  const { frameIndex, playing, active, script } = useDemo();
  const { stepIndex } = useTimeline();
  return (
    <p
      data-testid="probe"
      data-step={stepIndex}
      data-frame={frameIndex}
      data-playing={playing}
      data-active={active}
      data-frames={script?.frames.length ?? -1}
      data-total={script?.totalMs ?? -1}
    />
  );
};

const Harness = () => {
  const demo = useDemo();
  return (
    <>
      <Probe />
      <DemoControls playback={demo} />
      <DemoStage />
    </>
  );
};

const renderDemo = () =>
  render(
    <ThemeProvider>
      <I18nProvider>
        <ScenarioProvider>
          <TimelineProvider>
            <ConsoleProvider>
              <DemoProvider>
                <Harness />
              </DemoProvider>
            </ConsoleProvider>
          </TimelineProvider>
        </ScenarioProvider>
      </I18nProvider>
    </ThemeProvider>
  );

const probe = (): HTMLElement => screen.getByTestId('probe');

const eventOf = (): string | null | undefined =>
  screen
    .getByTestId('demo-caption')
    .querySelector('.demo-caption-text')
    ?.getAttribute('data-event');

beforeEach(() => {
  localStorage.clear();
  matchMedia(false);
  mockFetch();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('demo playback', () => {
  it('builds the walkthrough from the loaded document, not from constants', async () => {
    renderDemo();
    await waitFor(() => expect(probe().dataset.frames).toBe('3'));
    expect(probe().dataset.total).toBe('120');
  });

  it('shows nothing until the walkthrough is started', async () => {
    renderDemo();
    await screen.findByTestId('demo-start');
    expect(screen.queryByTestId('demo-caption')).toBeNull();
  });

  it('renders every caption from the event data of its step', async () => {
    renderDemo();
    fireEvent.click(await screen.findByTestId('demo-start'));
    const caption = await screen.findByTestId('demo-caption');
    expect(caption.textContent).toContain(ru['demo.caption.OVERVIEW']);
    expect(screen.getByTestId('demo-npv')).toBeTruthy();

    await waitFor(() => expect(eventOf()).toBe('MORPH'));
    await waitFor(() => expect(eventOf()).toBe('RULE_FIRED'));
    expect(screen.getByTestId('demo-caption').textContent).toContain('R1');
  });

  it('pauses on any user action and resumes from the current frame', async () => {
    renderDemo();
    fireEvent.click(await screen.findByTestId('demo-start'));
    await waitFor(() => expect(probe().dataset.playing).toBe('true'));

    act(() => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight' }));
    });
    await waitFor(() => expect(probe().dataset.playing).toBe('false'));
    const stopped = Number(probe().dataset.frame);
    expect(probe().dataset.active).toBe('true');

    fireEvent.click(screen.getByTestId('demo-toggle'));
    expect(probe().dataset.playing).toBe('true');
    expect(Number(probe().dataset.frame)).toBeGreaterThanOrEqual(stopped);
  });

  it('keeps playing when the demo transport itself is clicked', async () => {
    renderDemo();
    fireEvent.click(await screen.findByTestId('demo-start'));
    await waitFor(() => expect(probe().dataset.playing).toBe('true'));
    expect(screen.getByTestId('demo-toggle')).toBeTruthy();
    expect(probe().dataset.playing).toBe('true');
  });

  it('leaves the walkthrough when it is stopped', async () => {
    renderDemo();
    fireEvent.click(await screen.findByTestId('demo-start'));
    fireEvent.click(await screen.findByTestId('demo-stop'));
    await waitFor(() => expect(probe().dataset.active).toBe('false'));
    expect(screen.queryByTestId('demo-caption')).toBeNull();
  });
});

describe('reduced motion', () => {
  it('changes frames without travelling through the steps', async () => {
    vi.unstubAllGlobals();
    matchMedia(true);
    mockFetch();
    renderDemo();
    fireEvent.click(await screen.findByTestId('demo-start'));
    await waitFor(() => expect(eventOf()).toBe('RULE_FIRED'));
    await waitFor(() => expect(Number(probe().dataset.step)).toBe(30));
    expect(screen.getByTestId('demo-caption').textContent).toContain('R1');
  });

  it('travels through the intermediate steps when motion is allowed', async () => {
    renderDemo();
    fireEvent.click(await screen.findByTestId('demo-start'));
    await waitFor(() => expect(eventOf()).toBe('RULE_FIRED'));
    await waitFor(() => expect(Number(probe().dataset.step)).toBeGreaterThan(0));
    expect(Number(probe().dataset.step)).toBeLessThan(30);
  });
});
