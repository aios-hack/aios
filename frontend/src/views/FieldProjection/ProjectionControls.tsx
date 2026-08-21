import type { LayerRange } from '../../api/types';
import { useT } from '../../i18n/I18nContext';
import { watercutColor } from '../../theme/scales';
import type { LegendNote } from '../../ui/Legend';
import { LegendPopover } from '../../ui/Legend';
import { SegmentedControl } from '../../ui/SegmentedControl';
import { Slider } from '../../ui/Slider';
import { SettingsField, SettingsPopover, ViewToolbar } from '../../ui/ViewToolbar';
import { roundWeight } from '../shared/graphModel';
import { LayerFilterSwitch } from './LayerFilterSwitch';
import type { LayerFilter } from './layerFilter';

export type ProjectionPole = 'map' | 'graph';

interface ProjectionControlsProps {
  pole: ProjectionPole;
  t: number;
  threshold: number;
  thresholdMin: number;
  thresholdMax: number;
  shownEdges: number;
  totalEdges: number;
  layers: LayerRange[];
  layerFilter: LayerFilter;
  onPole: (pole: ProjectionPole) => void;
  onT: (value: number) => void;
  onThreshold: (value: number) => void;
  onLayerFilter: (filter: LayerFilter) => void;
  legendNotes: readonly LegendNote[];
}

export const ProjectionControls = ({
  pole,
  t,
  threshold,
  thresholdMin,
  thresholdMax,
  shownEdges,
  totalEdges,
  layers,
  layerFilter,
  onPole,
  onT,
  onThreshold,
  onLayerFilter,
  legendNotes
}: ProjectionControlsProps) => {
  const translate = useT();
  const step = Math.max((thresholdMax - thresholdMin) / 100, 0.001);

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
            onSelect={onPole}
          />
          <LayerFilterSwitch layers={layers} filter={layerFilter} onChange={onLayerFilter} />
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
            notes={[
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
              htmlFor="projection-blend"
              label={translate('projection.blend.label')}
              value={t.toFixed(2)}
              valueTestId="field-projection-t"
            >
              <Slider
                id="projection-blend"
                min={0}
                max={1}
                step={0.01}
                value={t}
                onChange={onT}
              />
            </SettingsField>
            <SettingsField
              htmlFor="projection-threshold"
              label={translate('projection.threshold.label')}
              value={String(roundWeight(threshold))}
            >
              <Slider
                id="projection-threshold"
                min={thresholdMin}
                max={thresholdMax}
                step={step}
                value={threshold}
                onChange={onThreshold}
              />
            </SettingsField>
          </SettingsPopover>
        </>
      }
    />
  );
};
