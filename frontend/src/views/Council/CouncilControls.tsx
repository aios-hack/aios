import { useT } from '../../i18n/I18nContext';
import { LegendPopover } from '../../ui/Legend';
import { ViewToolbar } from '../../ui/ViewToolbar';

export const CouncilControls = () => {
  const t = useT();

  return (
    <ViewToolbar
      right={
        <LegendPopover
          triggerLabel={t('toolbar.legend')}
          title={t('council.legend.title')}
          notes={[
            { text: t('council.legend.width') },
            { text: t('council.legend.color') },
            { text: t('council.legend.idle') },
            { text: t('council.legend.usage') },
            { text: t('council.legend.dim') },
            { text: t('council.legend.dash') }
          ]}
        />
      }
    />
  );
};
