import type { HighlightState } from '@/entities/wells/model/useSelectionHighlight';
import './SelectionRings.css';
import { clamp, clamp01 } from '@/shared/lib/math/clamp';

interface SelectionRingsProps {
  x: number;
  y: number;
  r: number;
  scale: number;
  state: HighlightState;
  groupColor: string | null;
  neighbourWeight: number;
}

export const GROUP_GAP = 0.55;
export const NEIGHBOUR_GAP = 1.2;
export const SELECT_GAP = 1.2;

export const STROKE_SHARE = 0.16;
export const MIN_STROKE = 0.11;
export const MAX_STROKE = 0.34;

export const MIN_NEIGHBOUR_OPACITY = 0.25;
export const MAX_NEIGHBOUR_OPACITY = 0.95;

export const ringStroke = (r: number, emphasis: number): number => {
  const derived = r * STROKE_SHARE * emphasis;
  return clamp(derived, MIN_STROKE, MAX_STROKE);
};

export const neighbourOpacity = (weight: number): number => {
  const share = clamp01(weight);
  return (
    MIN_NEIGHBOUR_OPACITY + share * (MAX_NEIGHBOUR_OPACITY - MIN_NEIGHBOUR_OPACITY)
  );
};

export const SelectionRings = ({
  x,
  y,
  r,
  scale,
  state,
  groupColor,
  neighbourWeight
}: SelectionRingsProps) => (
  <>
    {groupColor !== null && state !== 'faded' && (
      <circle
        className="selection-rings-group"
        data-group-ring={state === 'selected' ? 'strong' : 'plain'}
        cx={x}
        cy={y}
        r={r + GROUP_GAP / scale}
        fill="none"
        stroke={groupColor}
        strokeWidth={ringStroke(r, state === 'selected' ? 1 : 0.6)}
        opacity={state === 'selected' ? 1 : 0.55}
      />
    )}
    {state === 'selected' && (
      <circle
        className="selection-rings-select"
        data-testid="selection-rings-select"
        cx={x}
        cy={y}
        r={r + SELECT_GAP / scale}
        fill="none"
        strokeWidth={ringStroke(r, 1.15)}
      />
    )}
    {state === 'neighbour' && (
      <circle
        className="selection-rings-neighbour"
        data-neighbour-ring={state}
        cx={x}
        cy={y}
        r={r + NEIGHBOUR_GAP / scale}
        fill="none"
        strokeWidth={ringStroke(r, 0.8)}
        opacity={neighbourOpacity(neighbourWeight)}
      />
    )}
  </>
);
