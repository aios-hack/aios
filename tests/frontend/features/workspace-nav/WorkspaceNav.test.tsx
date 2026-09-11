import { render, screen, fireEvent } from '@testing-library/react';
import { readFileSync } from 'node:fs';
import { afterEach, describe, expect, it } from 'vitest';
import { I18nProvider } from '@/shared/i18n/I18nContext';
import { JarvisProvider } from '@/jarvis/provider/JarvisProvider';
import type { JarvisTransport } from '@/jarvis/transport/JarvisTransport';
import { RouterProvider, useRoute } from '@/shared/router/RouterProvider';
import { PlaybackProvider } from '@/entities/timeline/model/PlaybackContext';
import { ScenarioProvider } from '@/entities/scenarios/model/ScenarioContext';
import { TimelineProvider } from '@/entities/timeline/model/TimelineContext';
import { WorkspaceNav } from '@/features/workspace-nav/ui/WorkspaceNav/WorkspaceNav';
import { srcPath } from '@support/paths';

const silentTransport: JarvisTransport = {
  mode: 'mock',
  ask: async function* () {
    yield* [];
  }
};

const renderNav = () =>
  render(
    <I18nProvider>
      <RouterProvider>
        <WorkspaceNav />
      </RouterProvider>
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
    const css = readFileSync(srcPath('features', 'workspace-nav', 'ui', 'WorkspaceNav', 'WorkspaceNav.css'), 'utf-8');
    const activeRule = css.match(/\.workspace-nav-item\[data-active='true'\]\s*\{([^}]*)\}/);
    expect(activeRule).not.toBeNull();
    expect(activeRule?.[1]).toContain('--color-accent');
    expect(activeRule?.[1]).not.toContain('--color-text-muted');
  });
});

const ActiveWorkspaceProbe = () => {
  const { workspace } = useRoute();
  return <span data-testid="active-workspace">{workspace}</span>;
};

describe('WorkspaceNav arrow keys do not switch workspace', () => {
  it('ArrowDown never fires setWorkspace', () => {
    render(
      <I18nProvider>
        <RouterProvider>
          <WorkspaceNav />
          <ActiveWorkspaceProbe />
        </RouterProvider>
      </I18nProvider>
    );
    const tablist = screen.getByRole('tablist');
    const before = screen.getByTestId('active-workspace').textContent;
    fireEvent.keyDown(tablist, { key: 'ArrowDown' });
    fireEvent.keyDown(tablist, { key: 'ArrowDown' });
    expect(screen.getByTestId('active-workspace').textContent).toBe(before);
  });
});

const renderNavWithJarvis = () =>
  render(
    <I18nProvider>
      <ScenarioProvider>
        <TimelineProvider>
          <PlaybackProvider>
            <RouterProvider>
              <JarvisProvider transport={silentTransport}>
                <WorkspaceNav />
              </JarvisProvider>
            </RouterProvider>
          </PlaybackProvider>
        </TimelineProvider>
      </ScenarioProvider>
    </I18nProvider>
  );

describe('the Jarvis sphere sits under the workspaces without joining them', () => {
  it('is a button, not a tab, so the tablist keeps exactly five tabs', () => {
    renderNavWithJarvis();
    expect(screen.getAllByRole('tab').length).toBe(5);
    const launcher = screen.getByRole('button', { name: 'Открыть Джарвис' });
    expect(launcher.getAttribute('role')).toBeNull();
  });

  it('still exposes exactly one tab stop into the tablist', () => {
    renderNavWithJarvis();
    expect(screen.getAllByRole('tab').filter((tab) => tab.tabIndex === 0).length).toBe(1);
  });

  it('leaves the launcher out of the arrow-key ring of the tablist', () => {
    renderNavWithJarvis();
    const tablist = screen.getByRole('tablist');
    const launcher = screen.getByRole('button', { name: 'Открыть Джарвис' });
    expect(tablist.contains(launcher)).toBe(false);
  });

  it('announces its shortcut and its collapsed state', () => {
    renderNavWithJarvis();
    const launcher = screen.getByRole('button', { name: 'Открыть Джарвис' });
    expect(launcher.getAttribute('aria-keyshortcuts')).toBe('j');
    expect(launcher.getAttribute('aria-expanded')).toBe('false');
  });

  it('carries the visible name of the assistant next to the sphere', () => {
    renderNavWithJarvis();
    expect(screen.getByText('Джарвис')).toBeTruthy();
  });

  it('renders nothing extra when Jarvis is not mounted at all', () => {
    renderNav();
    expect(screen.queryByRole('button', { name: 'Открыть Джарвис' })).toBeNull();
    expect(screen.getAllByRole('tab').length).toBe(5);
  });
});
