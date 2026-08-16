import { fluidColors } from '../../theme/tokens';
import { trianglePath } from './geometry';

export type GaugeState = 'selected' | 'neighbour' | 'group' | 'plain' | 'faded';

interface WellGaugeProps {
  id: string;
  x: number;
  y: number;
  r: number;
  role: 'INJ' | 'PROD';
  watercut: number | null;
  commissioned: boolean;
  state: GaugeState;
  strokeWidth: number;
}

const stateOpacity = (state: GaugeState): number => (state === 'faded' ? 0.2 : 1);

export const WellGauge = ({
  id,
  x,
  y,
  r,
  role,
  watercut,
  commissioned,
  state,
  strokeWidth
}: WellGaugeProps) => {
  const outline = role === 'INJ' ? fluidColors.water : fluidColors.oil;
  const clipId = `gauge-clip-${id}`;
  const shape =
    role === 'INJ' ? (
      <path d={trianglePath(x, y, r)} />
    ) : (
      <circle cx={x} cy={y} r={r} />
    );

  if (!commissioned || watercut === null) {
    return (
      <g className="well-gauge" opacity={stateOpacity(state)} data-commissioned={commissioned}>
        {role === 'INJ' ? (
          <path
            d={trianglePath(x, y, r)}
            fill="none"
            stroke={outline}
            strokeWidth={strokeWidth}
            strokeDasharray={`${r * 0.5} ${r * 0.35}`}
          />
        ) : (
          <circle
            cx={x}
            cy={y}
            r={r}
            fill="none"
            stroke={outline}
            strokeWidth={strokeWidth}
            strokeDasharray={`${r * 0.5} ${r * 0.35}`}
          />
        )}
      </g>
    );
  }

  const level = Math.min(Math.max(watercut, 0), 1);
  const surface = y + r - 2 * r * level;

  return (
    <g className="well-gauge" opacity={stateOpacity(state)} data-commissioned="true">
      <defs>
        <clipPath id={clipId}>{shape}</clipPath>
      </defs>
      {role === 'INJ' ? (
        <path d={trianglePath(x, y, r)} fill={fluidColors.oil} />
      ) : (
        <circle cx={x} cy={y} r={r} fill={fluidColors.oil} />
      )}
      <rect
        x={x - r}
        y={surface}
        width={2 * r}
        height={2 * r}
        fill={fluidColors.water}
        clipPath={`url(#${clipId})`}
      />
      {role === 'INJ' ? (
        <path d={trianglePath(x, y, r)} fill="none" stroke={outline} strokeWidth={strokeWidth} />
      ) : (
        <circle cx={x} cy={y} r={r} fill="none" stroke={outline} strokeWidth={strokeWidth} />
      )}
    </g>
  );
};
