import type { MapWell } from '@/entities/maps/types';

interface PlacedWell {
  well: MapWell;
  x: number;
  y: number;
}

export const LABEL_CHAR_WIDTH_PX = 6.2;

export const LABEL_HEIGHT_PX = 12;

export const LABEL_PADDING_PX = 3;

interface Box {
  left: number;
  right: number;
  top: number;
  bottom: number;
}

const overlaps = (a: Box, b: Box): boolean =>
  a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;

export interface LabelCandidate {
  id: string;
  x: number;
  y: number;
  offsetPx: number;
}

export const labelBoxOf = (
  candidate: LabelCandidate,
  unitsPerPixel: number
): Box => {
  const width = candidate.id.length * LABEL_CHAR_WIDTH_PX + LABEL_PADDING_PX * 2;
  const left = candidate.x + candidate.offsetPx * unitsPerPixel;
  const top = candidate.y - (LABEL_HEIGHT_PX / 2) * unitsPerPixel;
  return {
    left,
    right: left + width * unitsPerPixel,
    top,
    bottom: top + LABEL_HEIGHT_PX * unitsPerPixel
  };
};

export const visibleLabels = (
  placements: readonly PlacedWell[],
  unitsPerPixel: number,
  offsetPx: number,
  pinned: readonly string[]
): Set<string> => {
  const shown = new Set<string>();
  const taken: Box[] = [];
  const pinnedSet = new Set(pinned);
  const ordered = [
    ...placements.filter((item) => pinnedSet.has(item.well.id)),
    ...placements.filter((item) => !pinnedSet.has(item.well.id))
  ];
  for (const { well, x, y } of ordered) {
    const candidate: LabelCandidate = { id: well.id, x, y, offsetPx };
    const box = labelBoxOf(candidate, unitsPerPixel);
    if (pinnedSet.has(well.id)) {
      shown.add(well.id);
      taken.push(box);
      continue;
    }
    if (taken.some((other) => overlaps(box, other))) {
      continue;
    }
    shown.add(well.id);
    taken.push(box);
  }
  return shown;
};
