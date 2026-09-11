import { useId } from 'react';
import type { GraphFile } from '@/entities/graph/types';
import type { LayerRange } from '@/entities/wells/types';
import { useI18n, type Translate } from '@/shared/i18n/I18nContext';
import type { Lang } from '@/shared/i18n/dictionaries';
import { watercutColor } from '@/shared/theme/scales';
import { InfoHint } from '@/shared/ui/InfoHint';
import type { LegendNote } from '@/shared/ui/Legend';
import { LegendPopover } from '@/shared/ui/Legend';
import { SegmentedControl } from '@/shared/ui/SegmentedControl';
import { Slider } from '@/shared/ui/Slider';
import { Switch } from '@/shared/ui/Switch';
import { formatNumber } from '@/shared/lib/format';
import { SettingsField, SettingsPopover, ViewToolbar } from '@/shared/ui/ViewToolbar';
import { roundWeight } from '@/entities/graph/model/graphModel';
import { LayerFilterSwitch } from '@/pages/field-projection/ui/LayerFilterSwitch/LayerFilterSwitch';
import type { LayerFilter } from '@/pages/field-projection/model/layerFilter';
import './ProjectionControls.css';
import { clamp01 } from '@/shared/lib/math/clamp';

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
  showGroups: boolean;
  onShowGroups: (value: boolean) => void;
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
  showGroups,
  onShowGroups,
  legendNotes
}: ProjectionControlsProps) => {
  const { t: translate, lang } = useI18n();
  const groupsId = useId();
  const span = Math.max(thresholdMax - thresholdMin, 1e-9);
  const toSlider = (value: number): number =>
    Math.sqrt(clamp01((value - thresholdMin) / span));
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
          <span className="projection-groups">
            <label className="projection-groups-label" htmlFor={groupsId}>
              {translate('projection.groups.label')}
            </label>
            <Switch
              id={groupsId}
              checked={showGroups}
              guide="projection-groups-toggle"
              testId="projection-groups-toggle"
              onChange={onShowGroups}
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
              { text: translate('projection.legend.ring.selected') },
              { text: translate('projection.legend.ring.neighbour') },
              { text: translate('projection.legend.fill') },
              { text: translate('projection.legend.groups') },
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
