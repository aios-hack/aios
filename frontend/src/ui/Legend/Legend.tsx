import './Legend.css';

const RAMP_STOPS = [0, 0.25, 0.5, 0.75, 1] as const;

export interface LegendRamp {
  colorAt: (stop: number) => string;
  lowLabel: string;
  highLabel: string;
}

export interface LegendSwatch {
  key: string;
  color: string;
  label: string;
}

export interface LegendNote {
  text: string;
  testId?: string;
}

export interface LegendProps {
  title: string;
  ramp?: LegendRamp;
  swatches?: readonly LegendSwatch[];
  notes?: readonly LegendNote[];
}

export const Legend = ({ title, ramp, swatches, notes }: LegendProps) => (
  <div className="legend" role="group" aria-label={title}>
    <p className="legend-title">{title}</p>
    {swatches !== undefined && swatches.length > 0 && (
      <ul className="legend-list">
        {swatches.map((swatch) => (
          <li key={swatch.key} className="legend-item">
            <span
              className="legend-swatch"
              style={{ background: swatch.color }}
              aria-hidden="true"
            />
            {swatch.label}
          </li>
        ))}
      </ul>
    )}
    {ramp !== undefined && (
      <>
        <ul className="legend-list legend-list--ramp" aria-hidden="true">
          {RAMP_STOPS.map((stop) => (
            <li
              key={stop}
              className="legend-band"
              style={{ background: ramp.colorAt(stop) }}
            />
          ))}
        </ul>
        <p className="legend-note">
          {ramp.lowLabel} → {ramp.highLabel}
        </p>
      </>
    )}
    {notes !== undefined &&
      notes.map((note) => (
        <p key={note.text} className="legend-note" data-testid={note.testId}>
          {note.text}
        </p>
      ))}
  </div>
);
