import { useEffect, useRef, useState } from 'react';
import type { MapLayerFile, MapScale, MapsIndexFile } from '@/entities/maps/types';
import { clamp01 } from '@/shared/theme/scales';
import { mixColors, readCssColor, readPalette, type Rgb } from '@/shared/lib/canvas/canvasColors';
import { categoryCount, categoryIndex, QUANT_MAX } from '@/pages/field-maps/model/mapModel';

const SEQ_NAMES = [
  '--color-map-seq-0',
  '--color-map-seq-1',
  '--color-map-seq-2',
  '--color-map-seq-3',
  '--color-map-seq-4',
  '--color-map-seq-5',
  '--color-map-seq-6'
] as const;

const CAT_NAMES = [
  '--color-map-cat-1',
  '--color-map-cat-2',
  '--color-map-cat-3',
  '--color-map-cat-4',
  '--color-map-cat-5',
  '--color-map-cat-6'
] as const;

const FALLBACK: Rgb = { r: 128, g: 128, b: 128, a: 1 };

export interface MapPalette {
  sequential: Rgb[];
  categorical: Rgb[];
  nodata: Rgb;
}

export const readMapPalette = (root: Element | null): MapPalette => {
  const seq = readPalette(SEQ_NAMES, FALLBACK, root);
  const cat = readPalette(CAT_NAMES, FALLBACK, root);
  return {
    sequential: SEQ_NAMES.map((name) => seq[name]),
    categorical: CAT_NAMES.map((name) => cat[name]),
    nodata: readCssColor('--color-map-nodata', root) ?? { r: 0, g: 0, b: 0, a: 0 }
  };
};

export const rampAt = (palette: readonly Rgb[], share: number): Rgb => {
  if (palette.length === 0) {
    return FALLBACK;
  }
  if (palette.length === 1) {
    return palette[0];
  }
  const position = clamp01(share) * (palette.length - 1);
  const low = Math.min(Math.floor(position), palette.length - 2);
  return mixColors(palette[low], palette[low + 1], position - low);
};

export const paintLayer = (
  target: ImageData,
  layer: MapLayerFile,
  index: MapsIndexFile,
  scale: MapScale,
  palette: MapPalette
): void => {
  const { ni, nj } = index;
  const pixels = target.data;
  const count = categoryCount(layer);
  for (let j = 0; j < nj; j += 1) {
    for (let i = 0; i < ni; i += 1) {
      const q = layer.q[j * ni + i];
      const at = ((nj - 1 - j) * ni + i) * 4;
      if (q === undefined || q === layer.nodata) {
        pixels[at] = Math.round(palette.nodata.r);
        pixels[at + 1] = Math.round(palette.nodata.g);
        pixels[at + 2] = Math.round(palette.nodata.b);
        pixels[at + 3] = Math.round(palette.nodata.a * 255);
        continue;
      }
      const colour =
        scale === 'categorical'
          ? palette.categorical[categoryIndex(layer, q) % palette.categorical.length] ??
            FALLBACK
          : rampAt(palette.sequential, count === 0 ? 0 : q / QUANT_MAX);
      pixels[at] = Math.round(colour.r);
      pixels[at + 1] = Math.round(colour.g);
      pixels[at + 2] = Math.round(colour.b);
      pixels[at + 3] = 255;
    }
  }
};

export const useMapPalette = (theme: string): MapPalette => {
  const [palette, setPalette] = useState<MapPalette>(() => readMapPalette(null));
  useEffect(() => {
    setPalette(readMapPalette(document.documentElement));
  }, [theme]);
  return palette;
};

export const useLayerCanvas = (
  layer: MapLayerFile | null,
  index: MapsIndexFile,
  scale: MapScale,
  palette: MapPalette
): string | null => {
  const [href, setHref] = useState<string | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    if (layer === null || typeof document === 'undefined') {
      setHref(null);
      return;
    }
    const canvas = canvasRef.current ?? document.createElement('canvas');
    canvasRef.current = canvas;
    canvas.width = index.ni;
    canvas.height = index.nj;
    const context = canvas.getContext('2d');
    if (context === null || typeof context.createImageData !== 'function') {
      setHref(null);
      return;
    }
    const image = context.createImageData(index.ni, index.nj);
    paintLayer(image, layer, index, scale, palette);
    context.putImageData(image, 0, 0);
    if (typeof canvas.toDataURL !== 'function') {
      setHref(null);
      return;
    }
    setHref(canvas.toDataURL());
  }, [layer, index, scale, palette]);

  return href;
};
