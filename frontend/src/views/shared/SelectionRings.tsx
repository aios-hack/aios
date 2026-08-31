import type { HighlightState } from '../WellCard/useSelectionHighlight';
import './SelectionRings.css';

interface SelectionRingsProps {
  x: number;
  y: number;
  r: number;
  scale: number;
  state: HighlightState;
  groupColor: string | null;
}

const inGroup = (state: HighlightState): boolean =>
  state === 'group' || state === 'selected';

const linked = (state: HighlightState): boolean =>
  state === 'neighbour' || state === 'selected';

export const GROUP_GAP = 0.55;
export const NEIGHBOUR_GAP = 1.2;
export const PULSE_GAP = 2.1;

export const STROKE_SHARE = 0.16;
export const MIN_STROKE = 0.11;
export const MAX_STROKE = 0.34;

export const ringStroke = (r: number, emphasis: number): number => {
  const derived = r * STROKE_SHARE * emphasis;
  return Math.min(Math.max(derived, MIN_STROKE), MAX_STROKE);
};

export const SelectionRings = ({
  x,
  y,
  r,
  scale,
  state,
  groupColor
}: SelectionRingsProps) => (
  <>
    {state === 'selected' && (
      <circle
        className="selection-rings-pulse"
        data-testid="selection-rings-pulse"
        cx={x}
        cy={y}
        r={r + PULSE_GAP / scale}
        fill="none"
        strokeWidth={ringStroke(r, 0.7)}
      />
    )}
    {groupColor !== null && state !== 'faded' && (
      <circle
        className="selection-rings-group"
        data-group-ring={inGroup(state) ? 'strong' : 'plain'}
        cx={x}
        cy={y}
        r={r + GROUP_GAP / scale}
        fill="none"
        stroke={groupColor}
        strokeWidth={ringStroke(r, inGroup(state) ? 1 : 0.6)}
        opacity={inGroup(state) ? 1 : 0.55}
      />
    )}
    {linked(state) && (
      <circle
        className="selection-rings-neighbour"
        data-neighbour-ring={state}
        cx={x}
        cy={y}
        r={r + NEIGHBOUR_GAP / scale}
        fill="none"
        strokeWidth={ringStroke(r, state === 'selected' ? 1.15 : 0.8)}
      />
    )}
  </>
);
