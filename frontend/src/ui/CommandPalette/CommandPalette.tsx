import { useEffect, useId, useMemo, useRef, type KeyboardEvent } from 'react';
import { useDataset } from '../../data';
import { useI18n } from '../../i18n/I18nContext';
import {
  useConsole,
  WORKSPACES,
  WORKSPACE_VIEWS,
  type Workspace,
  type WorkspaceView
} from '../../state/ConsoleContext';
import { useScenario } from '../../state/ScenarioContext';
import { useTimeline } from '../../state/TimelineContext';
import { formatStepDate } from '../format';
import { buildCommands, type Command } from './commands';
import { useCommandPalette } from './useCommandPalette';
import './CommandPalette.css';

export const CommandPalette = () => {
  const { t, lang } = useI18n();
  const { timeline, setStepIndex, selectWell } = useTimeline();
  const { selectScenario } = useScenario();
  const { setWorkspace, setView } = useConsole();
  const scenarios = useDataset('scenarios');
  const { open, query, active, setQuery, setActive, move, closePalette } =
    useCommandPalette();
  const uid = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);

  const steps = timeline.status === 'ready' ? timeline.data.steps : [];
  const wells = timeline.status === 'ready' ? timeline.data.wells : [];
  const entries = scenarios.status === 'ready' ? scenarios.data.scenarios : [];
  const actions = useMemo(() => {
    const navigation = WORKSPACES.flatMap((workspace) => [
      { id: `workspace:${workspace}`, label: t(`workspace.${workspace}`) },
      ...WORKSPACE_VIEWS[workspace].map((view) => ({
        id: `view:${workspace}:${view}`,
        label: `${t(`workspace.${workspace}`)} · ${t(`view.${view}`)}`
      }))
    ]);
    return navigation;
  }, [t]);

  const commands = useMemo(
    () =>
      buildCommands({
        wells,
        steps,
        scenarios: entries,
        actions,
        query,
        stepLabel: (step, index) =>
          t('palette.stepLabel', {
            date: formatStepDate(lang, step.date),
            step: index + 1
          })
      }),
    [wells, steps, entries, actions, query, t, lang]
  );

  useEffect(() => {
    if (open) {
      inputRef.current?.focus();
    }
  }, [open]);

  useEffect(() => {
    const node = listRef.current?.children[active];
    if (node instanceof HTMLElement && typeof node.scrollIntoView === 'function') {
      node.scrollIntoView({ block: 'nearest' });
    }
  }, [active, open]);

  if (!open) {
    return null;
  }

  const run = (command: Command | undefined) => {
    if (command === undefined) {
      return;
    }
    if (command.kind === 'action') {
      const [scope, workspace, view] = command.value.split(':');
      if (scope === 'workspace') {
        setWorkspace(workspace as Workspace);
      } else if (scope === 'view') {
        setWorkspace(workspace as Workspace);
        setView(view as WorkspaceView);
      }
    } else if (command.kind === 'well') {
      selectWell(command.value);
    } else if (command.kind === 'step') {
      setStepIndex(command.index);
    } else {
      selectScenario(command.value);
    }
    closePalette();
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      move(1, commands.length);
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      move(-1, commands.length);
    } else if (event.key === 'Enter') {
      event.preventDefault();
      run(commands[active]);
    } else if (event.key === 'Escape') {
      event.preventDefault();
      closePalette();
    } else if (event.key === 'Tab') {
      event.preventDefault();
    }
  };

  const activeId = commands.length === 0 ? undefined : `${uid}-${commands[active]?.id}`;

  return (
    <div
      className="palette-layer"
      data-testid="command-palette"
      onPointerDown={(event) => {
        if (event.target === event.currentTarget) {
          closePalette();
        }
      }}
    >
      <div
        className="palette"
        role="dialog"
        aria-modal="true"
        aria-label={t('palette.label')}
      >
        <div className="palette-field">
          <input
            ref={inputRef}
            type="text"
            role="combobox"
            className="palette-input"
            data-guide="palette-input"
            aria-label={t('palette.label')}
            aria-expanded
            aria-controls={`${uid}-list`}
            aria-autocomplete="list"
            aria-activedescendant={activeId}
            autoComplete="off"
            spellCheck={false}
            value={query}
            placeholder={t('palette.placeholder')}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={onKeyDown}
          />
          <span className="palette-count">{commands.length}</span>
        </div>
        <ul
          ref={listRef}
          id={`${uid}-list`}
          className="palette-list"
          role="listbox"
          aria-label={t('palette.label')}
        >
          {commands.map((command, index) => (
            <li
              key={command.id}
              id={`${uid}-${command.id}`}
              className="palette-option"
              role="option"
              aria-selected={index === active}
              data-kind={command.kind}
              onPointerMove={() => setActive(index)}
              onClick={() => run(command)}
            >
              <span className="palette-option-label">{command.label}</span>
              <span className="palette-option-kind">{t(`palette.kind.${command.kind}`)}</span>
            </li>
          ))}
        </ul>
        {commands.length === 0 && <p className="palette-empty">{t('palette.empty')}</p>}
      </div>
    </div>
  );
};
