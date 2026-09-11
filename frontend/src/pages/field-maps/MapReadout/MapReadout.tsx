import type { TimelineWellRow } from '@/entities/timeline/types';
import { actualRate } from '@/entities';
import { useI18n } from '@/shared/i18n/I18nContext';
import { AskJarvis } from '@/features/ask-jarvis/ui';
import { DASH, formatNumber, formatPercent } from '@/shared/lib/format';
import type { CellHit } from '@/pages/field-maps/mapModel';
import { clamp } from '@/shared/lib/math/clamp';

const READOUT_WIDTH = 236;
const READOUT_OFFSET = 14;

export interface MapHover {
  x: number;
  y: number;
  cell: CellHit | null;
  well: string | null;
}

export const readoutPlace = (
  hover: MapHover,
  box: { width: number; height: number }
): { left: number; top: number } => {
  const flip = hover.x + READOUT_OFFSET + READOUT_WIDTH > box.width;
  return {
    left: flip
      ? Math.max(0, hover.x - READOUT_OFFSET - READOUT_WIDTH)
      : hover.x + READOUT_OFFSET,
    top: clamp(hover.y, 0, box.height)
  };
};

interface MapReadoutProps {
  hover: MapHover;
  box: { width: number; height: number };
  propLabel: string;
  digits: number;
  layer: number;
  row: TimelineWellRow | undefined;
}

export const MapReadout = ({
  hover,
  box,
  propLabel,
  digits,
  layer,
  row
}: MapReadoutProps) => {
  const { t, lang } = useI18n();
  const place = readoutPlace(hover, box);
  const cell = hover.cell;

  return (
    <div
      className="field-maps-readout"
      data-testid="field-maps-readout"
      role="tooltip"
      style={{ left: `${place.left}px`, top: `${place.top}px`, width: `${READOUT_WIDTH}px` }}
    >
      <dl className="field-maps-readout-facts">
        <div className="field-maps-readout-fact">
          <dt>{t('maps.readout.cell')}</dt>
          <dd className="numeric">
            {cell === null ? DASH : `${cell.i + 1}, ${cell.j + 1}`}
          </dd>
        </div>
        <div className="field-maps-readout-fact">
          <dt>{propLabel}</dt>
          <dd className="numeric" data-testid="field-maps-readout-value">
            {cell === null || cell.value === null
              ? t('maps.readout.inactive')
              : formatNumber(lang, cell.value, digits)}
          </dd>
        </div>
        {hover.well !== null && (
          <div className="field-maps-readout-fact">
            <dt>{t('maps.readout.well')}</dt>
            <dd>{hover.well}</dd>
          </div>
        )}
        {row !== undefined && (
          <>
            <div className="field-maps-readout-fact">
              <dt>{t('maps.readout.status')}</dt>
              <dd>
                {row.availability === 'NOT_COMMISSIONED'
                  ? t('projection.tip.status.notCommissioned')
                  : row.operating_status === 'SHUT'
                    ? t('projection.tip.status.shut')
                    : t('projection.tip.status.open')}
              </dd>
            </div>
            <div className="field-maps-readout-fact">
              <dt>{t('maps.readout.bhp')}</dt>
              <dd className="numeric">{formatNumber(lang, row.bhp, 1)}</dd>
            </div>
            <div className="field-maps-readout-fact">
              <dt>{t('projection.tip.watercut')}</dt>
              <dd className="numeric">
                {row.watercut === null ? DASH : formatPercent(lang, row.watercut)}
              </dd>
            </div>
            <div className="field-maps-readout-fact">
              <dt>
                {t(row.role === 'INJ' ? 'projection.tip.injection' : 'projection.tip.liquid')}
              </dt>
              <dd className="numeric">{formatNumber(lang, actualRate(row), 1)}</dd>
            </div>
          </>
        )}
      </dl>
      {cell !== null && (
        <AskJarvis
          question={t('askJarvis.cell', {
            prop: propLabel,
            i: cell.i + 1,
            j: cell.j + 1,
            k: layer
          })}
          compact
          testId="ask-jarvis-cell"
        />
      )}
    </div>
  );
};
