import { useLayoutEffect, useRef, useState, type CSSProperties } from 'react';
import { JarvisLauncher } from '../../jarvis/JarvisLauncher';
import { useT } from '../../i18n/I18nContext';
import { useConsole, type Workspace } from '../../state/ConsoleContext';
import { useRovingTabs } from '../shared/useRovingTabs';
import './WorkspaceNav.css';

export const WorkspaceNav = () => {
  const t = useT();
  const { workspaces, workspace, setWorkspace } = useConsole();
  const refs = useRef<Map<string, HTMLButtonElement | null>>(new Map());
  const [thumb, setThumb] = useState<CSSProperties>({ opacity: 0 });
  const activeIndex = workspaces.indexOf(workspace);

  const { focusIndex, onKeyDown, getTabProps } = useRovingTabs({
    count: workspaces.length,
    activeIndex,
    orientation: 'vertical',
    activation: 'manual',
    onActivate: (index) => setWorkspace(workspaces[index])
  });

  useLayoutEffect(() => {
    const node = refs.current.get(workspace);
    if (!node) {
      return;
    }
    setThumb({
      opacity: 1,
      height: `${node.offsetHeight}px`,
      transform: `translateY(${node.offsetTop}px)`
    });
  }, [workspace, workspaces]);

  return (
    <nav className="workspace-nav" aria-label={t('nav.label')}>
      <div
        className="workspace-nav-tablist"
        role="tablist"
        aria-orientation="vertical"
        aria-label={t('nav.label')}
        onKeyDown={onKeyDown}
      >
        <span className="workspace-nav-thumb" style={thumb} aria-hidden="true" />
        {workspaces.map((id: Workspace, index: number) => {
          const tabProps = getTabProps(index);
          return (
            <button
              key={id}
              type="button"
              role="tab"
              className="workspace-nav-item"
              data-active={id === workspace}
              data-focused={index === focusIndex}
              aria-selected={id === workspace}
              tabIndex={tabProps.tabIndex}
              onFocus={tabProps.onFocus}
              ref={(node) => {
                refs.current.set(id, node);
                tabProps.ref(node);
              }}
              onClick={() => setWorkspace(id)}
            >
              {t(`workspace.${id}`)}
            </button>
          );
        })}
      </div>
      <JarvisLauncher />
    </nav>
  );
};
