import { render, screen, fireEvent } from '@testing-library/react';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';
import { I18nProvider } from '../../i18n/I18nContext';
import { ConsoleProvider, useConsole } from '../../state/ConsoleContext';
import { WorkspaceNav } from './WorkspaceNav';

const renderNav = () =>
  render(
    <I18nProvider>
      <ConsoleProvider>
        <WorkspaceNav />
      </ConsoleProvider>
    </I18nProvider>
  );

afterEach(() => {
  localStorage.clear();
});

describe('WorkspaceNav', () => {
  it('exposes exactly one tab stop into the tablist', () => {
    renderNav();
    const tabs = screen.getAllByRole('tab');
    const tabbable = tabs.filter((tab) => tab.tabIndex === 0);
    expect(tabbable.length).toBe(1);
  });

  it('moves focus with ArrowDown without changing the selected workspace', () => {
    renderNav();
    const tabs = screen.getAllByRole('tab');
    const tablist = screen.getByRole('tablist');
    const firstSelected = tabs.find((tab) => tab.getAttribute('aria-selected') === 'true');
    expect(firstSelected).toBeTruthy();
    fireEvent.keyDown(tablist, { key: 'ArrowDown' });
    expect(tabs.find((tab) => tab.getAttribute('aria-selected') === 'true')).toBe(firstSelected);
    fireEvent.focus(tabs[1]);
    expect(tabs[1].tabIndex).toBe(0);
  });

  it('Enter selects the focused tab and changes the workspace', () => {
    renderNav();
    const tabs = screen.getAllByRole('tab');
    const tablist = screen.getByRole('tablist');
    fireEvent.keyDown(tablist, { key: 'ArrowDown' });
    fireEvent.keyDown(tablist, { key: 'Enter' });
    expect(tabs[1].getAttribute('aria-selected')).toBe('true');
  });

  it('moves the thumb transform when the active workspace changes', () => {
    const { container } = renderNav();
    const tabs = screen.getAllByRole('tab');
    tabs.forEach((tab, index) => {
      Object.defineProperty(tab, 'offsetTop', { configurable: true, value: index * 40 });
      Object.defineProperty(tab, 'offsetHeight', { configurable: true, value: 34 });
    });
    fireEvent.click(tabs[0]);
    const thumb = container.querySelector('.workspace-nav-thumb') as HTMLElement;
    const before = thumb.style.transform;
    fireEvent.click(tabs[1]);
    const after = thumb.style.transform;
    expect(after).not.toBe(before);
  });
});

describe('WorkspaceNav active pill contrast', () => {
  it('styles the active item off aria-selected with accent text on the tinted fill, not the muted default', () => {
    const css = readFileSync(join(__dirname, 'WorkspaceNav.css'), 'utf-8');
    const activeRule = css.match(/\.workspace-nav-item\[data-active='true'\]\s*\{([^}]*)\}/);
    expect(activeRule).not.toBeNull();
    expect(activeRule?.[1]).toContain('--color-accent');
    expect(activeRule?.[1]).not.toContain('--color-text-muted');
  });
});

const ActiveWorkspaceProbe = () => {
  const { workspace } = useConsole();
  return <span data-testid="active-workspace">{workspace}</span>;
};

describe('WorkspaceNav arrow keys do not switch workspace', () => {
  it('ArrowDown never fires setWorkspace', () => {
    render(
      <I18nProvider>
        <ConsoleProvider>
          <WorkspaceNav />
          <ActiveWorkspaceProbe />
        </ConsoleProvider>
      </I18nProvider>
    );
    const tablist = screen.getByRole('tablist');
    const before = screen.getByTestId('active-workspace').textContent;
    fireEvent.keyDown(tablist, { key: 'ArrowDown' });
    fireEvent.keyDown(tablist, { key: 'ArrowDown' });
    expect(screen.getByTestId('active-workspace').textContent).toBe(before);
  });
});
