import { useMemo } from 'react';
import { createPortal } from 'react-dom';
import { useI18n } from '../../i18n/I18nContext';
import { useTimeline } from '../../state/TimelineContext';
import { WellCard } from '../../views/WellCard';
import { Inspector } from './Inspector';
import type { InspectorContext } from './InspectorContext';
import { useDeferredClose } from './useDeferredClose';

const VIEWS_WITH_WELLS = new Set<string>([
  'fund',
  'projection',
  'matrix',
  'wall',
  'table',
  'council',
  'rank'
]);

interface ConsoleInspectorProps {
  view?: string;
}

export const ConsoleInspector = ({ view }: ConsoleInspectorProps) => {
  const { t } = useI18n();
  const { selectedWell, selectWell } = useTimeline();

  const context = useMemo<InspectorContext | null>(
    () =>
      selectedWell !== null && (view === undefined || VIEWS_WITH_WELLS.has(view))
        ? { kind: 'well', well: selectedWell }
        : null,
    [selectedWell, view]
  );

  const { visible, closing } = useDeferredClose(context);

  if (visible === null) {
    return null;
  }

  const close = () => selectWell(null);

  return (
    <>
      {createPortal(
        <div
          className="console-scrim"
          data-closing={closing}
          data-testid="console-scrim"
          onClick={close}
          aria-hidden="true"
        />,
        document.body
      )}
      <Inspector
        context={visible}
        title={t('wellcard.title', { well: visible.well })}
        onClose={close}
        closing={closing}
      >
        <WellCard well={visible.well} />
      </Inspector>
    </>
  );
};
