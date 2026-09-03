import { useCallback, useEffect, useState } from 'react';
import {
  WORKSPACE_VIEWS,
  useConsole,
  type Workspace,
  type WorkspaceView
} from '../../state/ConsoleContext';
import { usePlayback } from '../../state/PlaybackContext';
import { useScenario } from '../../state/ScenarioContext';
import { useTimeline } from '../../state/TimelineContext';
import { applyConsoleAction, type ConsoleBridge } from './consoleActions';
import type { ConsoleAction } from './consoleAction';
import { spotlightAnchor } from './spotlight';

interface Pending {
  scenario: string;
  step?: number;
  well?: string | null;
  settled?: boolean;
}

export const useConsoleActions = (): ((action: ConsoleAction) => void) => {
  const { setRoute } = useConsole();
  const { activeId, selectScenario } = useScenario();
  const { timeline, stepIndex, setStepIndex, selectedWell, selectWell } = useTimeline();
  const { playing, togglePlay } = usePlayback();
  const stepCount = timeline.status === 'ready' ? timeline.data.steps.length : 0;
  const [pending, setPending] = useState<Pending | null>(null);
  const current = activeId === '' ? 'base' : activeId;

  useEffect(() => {
    const waiting = pending;
    if (waiting === null || waiting.scenario !== current || stepCount === 0) {
      return;
    }
    const step =
      waiting.step === undefined
        ? undefined
        : Math.min(Math.max(Math.trunc(waiting.step), 0), stepCount - 1);
    const stepSettled = step === undefined || stepIndex === step;
    const wellSettled = waiting.well === undefined || selectedWell === waiting.well;
    if (stepSettled && wellSettled) {
      if (waiting.settled) {
        setPending(null);
      } else {
        setPending({ ...waiting, settled: true });
      }
      return;
    }
    if (step !== undefined) {
      setStepIndex(step);
    }
    if (waiting.well !== undefined) {
      selectWell(waiting.well);
    }
  }, [pending, current, stepCount, stepIndex, selectedWell, setStepIndex, selectWell]);

  return useCallback(
    (action: ConsoleAction) => {
      if (action.scenario !== undefined && action.scenario !== current) {
        setPending({
          scenario: action.scenario,
          step: action.step,
          well: action.well
        });
      }
      const bridge: ConsoleBridge = {
        setRoute,
        selectScenario,
        setStepIndex: (index: number) => setStepIndex(index),
        selectWell,
        togglePlay,
        playing,
        stepCount,
        currentScenario: current,
        defaultViewOf: (workspace: Workspace): WorkspaceView => WORKSPACE_VIEWS[workspace][0],
        spotlight: (anchor: string) => {
          requestAnimationFrame(() => {
            requestAnimationFrame(() => {
              spotlightAnchor(anchor);
            });
          });
        }
      };
      applyConsoleAction(action, bridge);
    },
    [setRoute, selectScenario, setStepIndex, selectWell, togglePlay, playing, stepCount, current]
  );
};
