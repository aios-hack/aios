import { useMemo } from 'react';
import { useI18n } from '../../i18n/I18nContext';
import { useTimeline } from '../../state/TimelineContext';
import { WellCard } from '../../views/WellCard';
import { Inspector } from './Inspector';
import type { InspectorContext } from './InspectorContext';
import { ScenarioInspector } from './ScenarioInspector';
import { useDeferredClose } from './useDeferredClose';

interface ConsoleInspectorProps {
  scenarioContext: InspectorContext | null;
  onCloseScenario: () => void;
}

export const ConsoleInspector = ({
  scenarioContext,
  onCloseScenario
}: ConsoleInspectorProps) => {
  const { t } = useI18n();
  const { selectedWell, selectWell } = useTimeline();

  const wellContext = useMemo<InspectorContext | null>(
    () => (selectedWell !== null ? { kind: 'well', well: selectedWell } : null),
    [selectedWell]
  );
  const context = wellContext ?? scenarioContext;

  const { visible, closing } = useDeferredClose(context);

  if (visible === null) {
    return null;
  }

  const close = () => (visible.kind === 'well' ? selectWell(null) : onCloseScenario());
  const title =
    visible.kind === 'well'
      ? t('wellcard.title', { well: visible.well })
      : t('inspector.scenario.title', { id: visible.scenarioId });

  return (
    <Inspector context={visible} title={title} onClose={close} closing={closing}>
      {visible.kind === 'well' ? (
        <WellCard well={visible.well} />
      ) : (
        <ScenarioInspector scenarioId={visible.scenarioId} />
      )}
    </Inspector>
  );
};
