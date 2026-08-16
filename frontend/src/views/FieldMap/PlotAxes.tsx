import type { GridSize } from '../../api/types';

const TICK_STEP = 10;
const TICK_LEN = 1.8;
const TICK_GAP = 2.4;
const AXIS_OVERSHOOT = 6;
const LABEL_SIZE = 4.4;
const TICK_SIZE = 2.4;

const ticksFor = (size: number): number[] => {
  const ticks: number[] = [];
  for (let value = TICK_STEP; value < size; value += TICK_STEP) {
    ticks.push(value);
  }
  return ticks;
};

interface PlotAxesProps {
  grid: GridSize;
  axisI: string;
  axisJ: string;
}

export const PlotAxes = ({ grid, axisI, axisJ }: PlotAxesProps) => (
  <g className="plot-axes" aria-hidden="true">
    <defs>
      <marker
        id="axis-arrow"
        viewBox="0 0 10 10"
        refX="8"
        refY="5"
        markerWidth="5"
        markerHeight="5"
        orient="auto-start-reverse"
      >
        <path d="M 0 1 L 9 5 L 0 9 z" fill="currentColor" />
      </marker>
    </defs>

    <line
      x1={0}
      y1={0}
      x2={grid.ni + AXIS_OVERSHOOT}
      y2={0}
      markerEnd="url(#axis-arrow)"
      className="plot-axis-line"
    />
    <line
      x1={0}
      y1={0}
      x2={0}
      y2={grid.nj + AXIS_OVERSHOOT}
      markerEnd="url(#axis-arrow)"
      className="plot-axis-line"
    />

    <text x={grid.ni + AXIS_OVERSHOOT + 3} y={1.6} fontSize={LABEL_SIZE} className="plot-axis-name">
      {axisI}
    </text>
    <text x={-1.6} y={grid.nj + AXIS_OVERSHOOT + 4} fontSize={LABEL_SIZE} className="plot-axis-name">
      {axisJ}
    </text>

    <text
      x={-1.2}
      y={-1.2}
      fontSize={TICK_SIZE}
      textAnchor="end"
      className="plot-tick-label plot-tick-label--edge"
    >
      0
    </text>

    {ticksFor(grid.ni).map((value) => (
      <g key={`i-${value}`}>
        <line x1={value} y1={0} x2={value} y2={-TICK_LEN} className="plot-tick" />
        <text
          x={value}
          y={-TICK_LEN - TICK_GAP}
          fontSize={TICK_SIZE}
          textAnchor="middle"
          className="plot-tick-label"
        >
          {value}
        </text>
      </g>
    ))}

    {ticksFor(grid.nj).map((value) => (
      <g key={`j-${value}`}>
        <line x1={0} y1={value} x2={-TICK_LEN} y2={value} className="plot-tick" />
        <text
          x={-TICK_LEN - TICK_GAP}
          y={value}
          fontSize={TICK_SIZE}
          textAnchor="end"
          dominantBaseline="middle"
          className="plot-tick-label"
        >
          {value}
        </text>
      </g>
    ))}

  </g>
);
