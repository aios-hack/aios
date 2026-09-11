import type { TimelineWellRow } from '@/entities/timeline/types';
import { actualRate } from '@/entities';
import { useI18n } from '@/shared/i18n/I18nContext';
import { AskJarvis } from '@/features/ask-jarvis/ui';
import { DASH, formatNumber, formatPercent } from '@/shared/lib/format';
import { clamp } from '@/shared/lib/math/clamp';

const TOOLTIP_WIDTH = 232;
const TOOLTIP_OFFSET = 14;

export interface NodeHover {
  well: string;
  x: number;
  y: number;
}

export interface TooltipBox {
  width: number;
  height: number;
}

interface NodeTooltipProps {
  hover: NodeHover;
  box: TooltipBox;
  row: TimelineWellRow | undefined;
  step: number;
}

export const tooltipStyle = (
  hover: NodeHover,
  box: TooltipBox
): { left: number; top: number } => {
  const flipX = hover.x + TOOLTIP_OFFSET + TOOLTIP_WIDTH > box.width;
  const left = flipX
    ? Math.max(0, hover.x - TOOLTIP_OFFSET - TOOLTIP_WIDTH)
    : hover.x + TOOLTIP_OFFSET;
  return { left, top: clamp(hover.y, 0, box.height) };
};

export const NodeTooltip = ({ hover, box, row, step }: NodeTooltipProps) => {
  const { t, lang } = useI18n();
  const place = tooltipStyle(hover, box);
  const role =
    row === undefined
      ? DASH
      : t(row.role === 'INJ' ? 'projection.tip.injector' : 'projection.tip.producer');
  const status =
    row === undefined
      ? DASH
      : row.availability === 'NOT_COMMISSIONED'
        ? t('projection.tip.status.notCommissioned')
        : row.operating_status === 'SHUT'
          ? t('projection.tip.status.shut')
          : t('projection.tip.status.open');
  const rate = row === undefined ? DASH : formatNumber(lang, actualRate(row), 1);
  const watercut =
    row === undefined || row.watercut === null ? DASH : formatPercent(lang, row.watercut);

  return (
    <div
      className="projection-tooltip"
      data-testid="projection-tooltip"
      role="tooltip"
      style={{ left: `${place.left}px`, top: `${place.top}px`, width: `${TOOLTIP_WIDTH}px` }}
    >
      <p className="projection-tooltip-well">{hover.well}</p>
      <dl className="projection-tooltip-facts">
        <div className="projection-tooltip-fact">
          <dt>{t('projection.tip.role')}</dt>
          <dd>{role}</dd>
        </div>
        <div className="projection-tooltip-fact">
          <dt>{t('projection.tip.statusLabel')}</dt>
          <dd>{status}</dd>
        </div>
        <div className="projection-tooltip-fact">
          <dt>
            {t(
              row !== undefined && row.role === 'INJ'
                ? 'projection.tip.injection'
                : 'projection.tip.liquid'
            )}
          </dt>
          <dd className="numeric">{rate}</dd>
        </div>
        <div className="projection-tooltip-fact">
          <dt>{t('projection.tip.watercut')}</dt>
          <dd className="numeric">{watercut}</dd>
        </div>
      </dl>
      <AskJarvis
        question={t('askJarvis.well', { well: hover.well, step })}
        compact
        testId={`ask-jarvis-node-${hover.well}`}
      />
    </div>
  );
};
