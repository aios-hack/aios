import { act, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ConsoleProvider, useConsole } from './ConsoleContext';

const Probe = () => {
  const { morphRequest, requestMorph } = useConsole();
  return (
    <div>
      <span data-testid="value">{morphRequest === null ? 'none' : morphRequest.value}</span>
      <span data-testid="serial">{morphRequest === null ? 0 : morphRequest.serial}</span>
      <button type="button" onClick={() => requestMorph(1)}>
        connectivity
      </button>
      <button type="button" onClick={() => requestMorph(0)}>
        map
      </button>
      <button type="button" onClick={() => requestMorph(4.5)}>
        beyond
      </button>
    </div>
  );
};

const renderProbe = () =>
  render(
    <ConsoleProvider>
      <Probe />
    </ConsoleProvider>
  );

const press = (name: string) => act(() => screen.getByRole('button', { name }).click());

describe('morph requests', () => {
  it('carries nothing until the scene is asked to travel', () => {
    renderProbe();
    expect(screen.getByTestId('value').textContent).toBe('none');
  });

  it('passes the requested pole through to whoever renders the projection', () => {
    renderProbe();
    press('connectivity');
    expect(screen.getByTestId('value').textContent).toBe('1');
  });

  it('marks a repeated request as new so the same pole can be replayed', () => {
    renderProbe();
    press('connectivity');
    const first = screen.getByTestId('serial').textContent;
    press('connectivity');
    expect(screen.getByTestId('serial').textContent).not.toBe(first);
    expect(screen.getByTestId('value').textContent).toBe('1');
  });

  it('counts every request so the projection can tell them apart in order', () => {
    renderProbe();
    press('connectivity');
    press('map');
    expect(screen.getByTestId('value').textContent).toBe('0');
    expect(screen.getByTestId('serial').textContent).toBe('2');
  });

  it('clamps a value outside the interpolation range instead of trusting it', () => {
    renderProbe();
    press('beyond');
    expect(screen.getByTestId('value').textContent).toBe('1');
  });
});
