import { useMemo } from 'react';
import { createPortal } from 'react-dom';
import { useI18n } from '@/shared/i18n/I18nContext';
import { useTimeline } from '@/entities/timeline/model/TimelineContext';
import { WellCard } from '@/features/inspector/ui/WellCard';
import { useOverlayHost } from '@/shared/lib/overlay';
import { Inspector } from '@/features/inspector/ui/Inspector/Inspector';
import type { InspectorContext } from '@/features/inspector/ui/InspectorContext';
import { useDeferredClose } from '@/shared/lib/transition/useDeferredClose';

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
  const host = useOverlayHost();

  const context = useMemo<InspectorContext | null>(
    () =>
      selectedWell !== null && (view === undefined || VIEWS_WITH_WELLS.has(view))
        ? { kind: 'well', well: selectedWell }
        : null,
    [selectedWell, view]
  );

  const { visible, closing } = useDeferredClose(context);

  if (visible === null || host === null) {
    return null;
  }

  const close = () => selectWell(null);

  return createPortal(
    <>
      <div
        className="console-scrim"
        data-closing={closing}
        data-testid="console-scrim"
        onClick={close}
        aria-hidden="true"
      />
      <div className="console-area-inspector">
        <Inspector
          context={visible}
          title={t('wellcard.title', { well: visible.well })}
          onClose={close}
          closing={closing}
        >
          <WellCard well={visible.well} />
        </Inspector>
      </div>
    </>,
    host
  );
};
