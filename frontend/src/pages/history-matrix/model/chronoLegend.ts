import type { Translate } from '@/shared/i18n/I18nContext';
import { chronoModeColors } from '@/shared/theme/tokens';
import type { LegendSwatch } from '@/shared/ui/Legend';

export const CHRONO_MODES = ['production', 'injection', 'shut', 'idle'] as const;

export interface LegendNote {
  text: string;
  testId?: string;
}

export const modeSwatchesOf = (
  metric: string,
  t: Translate
): LegendSwatch[] | undefined =>
  metric === 'mode'
    ? CHRONO_MODES.map((mode) => ({
        key: mode,
        color: chronoModeColors[mode],
        label: t(`chrono.mode.${mode}`)
      }))
    : undefined;

interface LegendNoteInputs {
  metric: string;
  wells: number;
  steps: number;
  ungrouped: number;
  t: Translate;
}

export const legendNotesOf = ({
  metric,
  wells,
  steps,
  ungrouped,
  t
}: LegendNoteInputs): LegendNote[] => [
  { text: t('chrono.size', { wells, steps }), testId: 'chrono-legend-size' },
  { text: t('chrono.legend.terminal') },
  ...(metric === 'npv' ? [{ text: t('chrono.npvNote') }] : []),
  {
    text:
      ungrouped > 0
        ? t('chrono.ungrouped', { count: ungrouped })
        : t('chrono.ungroupedNone')
  }
];
