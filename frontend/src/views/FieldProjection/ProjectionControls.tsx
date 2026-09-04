import type { GraphFile, LayerRange } from '../../api/types';
import { useI18n, type Translate } from '../../i18n/I18nContext';
import type { Lang } from '../../i18n/dictionaries';
import { watercutColor } from '../../theme/scales';
import { InfoHint } from '../../ui/InfoHint';
import type { LegendNote } from '../../ui/Legend';
import { LegendPopover } from '../../ui/Legend';
import { SegmentedControl } from '../../ui/SegmentedControl';
import { Slider } from '../../ui/Slider';
import { formatNumber } from '../../ui/format';
import { SettingsField, SettingsPopover, ViewToolbar } from '../../ui/ViewToolbar';
import { roundWeight } from '../shared/graphModel';
import { LayerFilterSwitch } from './LayerFilterSwitch';
import type { LayerFilter } from './layerFilter';
import './ProjectionControls.css';

export type ProjectionPole = 'map' | 'graph';

export type EdgesMeta = (GraphFile['meta'] & { lambda_measured?: boolean }) | undefined;

const isNumber = (value: unknown): value is number =>
  typeof value === 'number' && Number.isFinite(value);

export const edgesHintText = (meta: EdgesMeta, t: Translate, lang: Lang): string => {
  if (
    meta === undefined ||
    meta.lambda_measured !== true ||
    !isNumber(meta.lag_months) ||
    !isNumber(meta.stability) ||
    !isNumber(meta.rank) ||
    !isNumber(meta.condition_number)
  ) {
    return t('projection.edges.hint.unmeasured');
  }
  return t('projection.edges.hint.measured', {
    lag:
      meta.lag_months === 0
        ? t('projection.edges.lagZero')
        : t('projection.edges.lagMonths', { value: formatNumber(lang, meta.lag_months) }),
    stability: formatNumber(lang, meta.stability, 2),
    rank: formatNumber(lang, meta.rank),
    condition: formatNumber(lang, meta.condition_number, 1)
  });
};

interface ProjectionControlsProps {
  pole: ProjectionPole;
  threshold: number;
  thresholdMin: number;
  thresholdMax: number;
  shownEdges: number;
  totalEdges: number;
  layers: LayerRange[];
  layerFilter: LayerFilter;
  edgesMeta: EdgesMeta;
  onPole: (pole: ProjectionPole) => void;
  onThreshold: (value: number) => void;
  onLayerFilter: (filter: LayerFilter) => void;
  legendNotes: readonly LegendNote[];
}

export const ProjectionControls = ({
  pole,
  threshold,
  thresholdMin,
  thresholdMax,
  shownEdges,
  totalEdges,
  layers,
  layerFilter,
  edgesMeta,
  onPole,
  onThreshold,
  onLayerFilter,
  legendNotes
}: ProjectionControlsProps) => {
  const { t: translate, lang } = useI18n();
  const span = Math.max(thresholdMax - thresholdMin, 1e-9);
  const toSlider = (value: number): number =>
    Math.sqrt(Math.min(Math.max((value - thresholdMin) / span, 0), 1));
  const fromSlider = (position: number): number =>
    thresholdMin + position * position * span;

  return (
    <ViewToolbar
      left={
        <>
          <SegmentedControl
            options={[
              { value: 'graph' as const, label: translate('projection.pole.graph') },
              { value: 'map' as const, label: translate('projection.pole.map') }
            ]}
            active={pole}
            label={translate('projection.poleLabel')}
            guide="projection-pole-control"
            onSelect={onPole}
          />
          <LayerFilterSwitch layers={layers} filter={layerFilter} onChange={onLayerFilter} />
          <span
            className="projection-edges-hint"
            data-guide="projection-edges-hint"
            data-testid="projection-edges-hint"
          >
            <InfoHint
              label={translate('projection.edges.hint.label')}
              text={edgesHintText(edgesMeta, translate, lang)}
            />
          </span>
        </>
      }
      right={
        <>
          <LegendPopover
            triggerLabel={translate('toolbar.legend')}
            title={translate('projection.legend.title')}
            ramp={{
              colorAt: (stop) => watercutColor(stop),
              lowLabel: translate('chrono.legend.low.watercut'),
              highLabel: translate('chrono.legend.high.watercut')
            }}
            swatches={[
              {
                key: 'edge-positive',
                color: 'var(--color-edge-positive)',
                label: translate('projection.legend.edge.positive')
              },
              {
                key: 'edge-negative',
                color: 'var(--color-edge-negative)',
                label: translate('projection.legend.edge.negative')
              }
            ]}
            notes={[
              { text: translate('projection.legend.shape.producer') },
              { text: translate('projection.legend.shape.injector') },
              { text: translate('projection.legend.size') },
              { text: translate('projection.legend.edge.width') },
              { text: translate('projection.legend.pole.explain') },
              { text: translate('projection.legend.selection') },
              {
                text: translate('projection.threshold.edges', {
                  shown: shownEdges,
                  total: totalEdges
                })
              },
              ...legendNotes
            ]}
          />
          <SettingsPopover
            label={translate('toolbar.settings')}
            title={translate('toolbar.settings')}
          >
            <SettingsField
              htmlFor="projection-threshold"
              label={translate('projection.threshold.label')}
              value={String(roundWeight(threshold))}
            >
              <Slider
                id="projection-threshold"
                min={0}
                max={1}
                step={0.01}
                value={toSlider(threshold)}
                guide="projection-threshold-slider"
                onChange={(position) => onThreshold(fromSlider(position))}
              />
            </SettingsField>
          </SettingsPopover>
        </>
      }
    />
  );
};
