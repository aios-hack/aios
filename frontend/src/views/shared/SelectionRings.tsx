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

export const SelectionRings = ({
  x,
  y,
  r,
  scale,
  state,
  groupColor
}: SelectionRingsProps) => (
  <>
    {groupColor !== null && state !== 'faded' && (
      <circle
        className="selection-rings-group"
        data-group-ring={inGroup(state) ? 'strong' : 'plain'}
        cx={x}
        cy={y}
        r={r * 1.75}
        fill="none"
        stroke={groupColor}
        strokeWidth={(inGroup(state) ? 0.9 : 0.4) / scale}
        opacity={inGroup(state) ? 1 : 0.55}
      />
    )}
    {linked(state) && (
      <circle
        className="selection-rings-neighbour"
        data-neighbour-ring={state}
        cx={x}
        cy={y}
        r={r * 2.3}
        fill="none"
        strokeWidth={(state === 'selected' ? 1.1 : 0.7) / scale}
      />
    )}
  </>
);
