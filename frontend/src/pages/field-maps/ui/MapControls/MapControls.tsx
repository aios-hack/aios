import { useId } from 'react';
import type { MapLayerFile, MapPropRef, MapsIndexFile } from '@/entities/maps/types';
import { useI18n } from '@/shared/i18n/I18nContext';
import { mapRampColor } from '@/shared/theme/scales';
import { mapCategoryColor } from '@/shared/theme/tokens';
import { LegendPopover } from '@/shared/ui/Legend';
import { SegmentedControl } from '@/shared/ui/SegmentedControl';
import { Slider } from '@/shared/ui/Slider';
import { Switch } from '@/shared/ui/Switch';
import { formatNumber } from '@/shared/lib/format';
import { SettingsField, SettingsPopover, ViewToolbar } from '@/shared/ui/ViewToolbar';
import { categoryCount, presetsOf } from '@/pages/field-maps/model/mapModel';
import './MapControls.css';

interface MapControlsProps {
  index: MapsIndexFile;
  props: readonly MapPropRef[];
  prop: MapPropRef;
  layer: MapLayerFile | null;
  k: number;
  kMin: number;
  kMax: number;
  showWells: boolean;
  showLabels: boolean;
  onProp: (id: string) => void;
  onLayer: (k: number) => void;
  onShowWells: (value: boolean) => void;
  onShowLabels: (value: boolean) => void;
}

const digitsFor = (scale: string): number => (scale === 'categorical' ? 0 : 3);

export const MapControls = ({
  index,
  props,
  prop,
  layer,
  k,
  kMin,
  kMax,
  showWells,
  showLabels,
  onProp,
  onLayer,
  onShowWells,
  onShowLabels
}: MapControlsProps) => {
  const { t, lang } = useI18n();
  const wellsId = useId();
  const labelsId = useId();
  const presets = presetsOf(index);
  const categorical = prop.scale === 'categorical';
  const count = layer === null ? 0 : categoryCount(layer);

  return (
    <ViewToolbar
      left={
        <>
          <SegmentedControl
            options={props.map((item) => ({
              value: item.id,
              label: t(`maps.prop.${item.id}`)
            }))}
            active={prop.id}
            label={t('maps.propLabel')}
            guide="maps-prop-tabs"
            onSelect={onProp}
          />
          <span className="map-presets" data-testid="maps-presets">
            {presets.map((preset) => (
              <button
                key={preset.id}
                type="button"
                className="map-preset"
                data-active={k >= preset.kMin && k <= preset.kMax}
                onClick={() => onLayer(preset.kMin)}
              >
                {t('maps.preset', {
                  id: preset.id,
                  from: preset.kMin,
                  to: preset.kMax
                })}
              </button>
            ))}
          </span>
        </>
      }
      center={
        <span className="map-layer" data-guide="maps-layer-slider">
          <label className="map-layer-label" htmlFor="maps-layer">
            {t('maps.layer')}
          </label>
          <Slider
            id="maps-layer"
            className="map-layer-slider"
            min={kMin}
            max={kMax}
            step={1}
            value={k}
            ariaLabel={t('maps.layer')}
            onChange={onLayer}
          />
          <output
            className="map-layer-value numeric"
            htmlFor="maps-layer"
            data-testid="maps-layer-value"
          >
            {k}
          </output>
        </span>
      }
      right={
        <>
          <LegendPopover
            triggerLabel={t('toolbar.legend')}
            guide="maps-legend"
            title={t('maps.legend.title', { prop: t(`maps.prop.${prop.id}`) })}
            ramp={
              categorical || layer === null
                ? undefined
                : {
                    colorAt: (stop) => mapRampColor(stop),
                    lowLabel: formatNumber(lang, layer.min, digitsFor(prop.scale)),
                    highLabel: formatNumber(lang, layer.max, digitsFor(prop.scale))
                  }
            }
            swatches={
              categorical && layer !== null
                ? Array.from({ length: Math.min(count, 6) }, (_, index) => ({
                    key: String(index),
                    color: mapCategoryColor(index),
                    label: `${t(`maps.prop.${prop.id}`)} ${Math.round(layer.min) + index}`
                  }))
                : undefined
            }
            notes={[
              { text: t(`maps.scale.${prop.scale}`) },
              { text: t('maps.legend.nodata') },
              { text: t('maps.legend.wellFill') },
              { text: t('maps.legend.wellRing') },
              { text: t('maps.legend.wellShape') }
            ]}
          />
          <SettingsPopover label={t('toolbar.settings')} title={t('toolbar.settings')}>
            <SettingsField
              htmlFor={wellsId}
              label={t('maps.showWells')}
              value={t(showWells ? 'maps.on' : 'maps.off')}
            >
              <Switch
                id={wellsId}
                checked={showWells}
                testId="maps-wells-toggle"
                onChange={onShowWells}
              />
            </SettingsField>
            <SettingsField
              htmlFor={labelsId}
              label={t('maps.showLabels')}
              value={t(showLabels ? 'maps.on' : 'maps.off')}
            >
              <Switch
                id={labelsId}
                checked={showLabels}
                testId="maps-labels-toggle"
                onChange={onShowLabels}
              />
            </SettingsField>
          </SettingsPopover>
        </>
      }
    />
  );
};
