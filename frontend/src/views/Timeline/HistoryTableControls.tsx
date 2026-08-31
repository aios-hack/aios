import { useT } from '../../i18n/I18nContext';
import { LegendPopover } from '../../ui/Legend';
import { ViewToolbar } from '../../ui/ViewToolbar';

export const HistoryTableControls = () => {
  const t = useT();

  return (
    <ViewToolbar
      right={
        <LegendPopover
          triggerLabel={t('toolbar.legend')}
          title={t('steps.legend.title')}
          notes={[
            { text: t('steps.legend.step') },
            { text: t('steps.legend.setpoint') },
            { text: t('steps.legend.dash') },
            { text: t('steps.legend.selected') },
            { text: t('steps.legend.sort') },
            { text: t('steps.legend.marks') },
            { text: t('steps.legend.cursorDot') }
          ]}
        />
      }
    />
  );
};
