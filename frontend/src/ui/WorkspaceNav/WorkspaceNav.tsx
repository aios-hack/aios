import { useT } from '../../i18n/I18nContext';
import { useConsole, type Workspace } from '../../state/ConsoleContext';
import './WorkspaceNav.css';

export const WorkspaceNav = () => {
  const t = useT();
  const { workspaces, workspace, setWorkspace } = useConsole();

  return (
    <nav className="workspace-nav" aria-label={t('nav.label')}>
      {workspaces.map((id: Workspace) => (
        <button
          key={id}
          type="button"
          className="workspace-nav-item"
          data-active={id === workspace}
          aria-current={id === workspace ? 'true' : undefined}
          onClick={() => setWorkspace(id)}
        >
          {t(`workspace.${id}`)}
        </button>
      ))}
    </nav>
  );
};
