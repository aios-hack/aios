import './Legend.css';

const RAMP_STOPS = [0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1] as const;

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
        <span
          className="legend-ramp"
          aria-hidden="true"
          style={{
            backgroundImage: `linear-gradient(to right, ${RAMP_STOPS.map(
              (stop) => `${ramp.colorAt(stop)} ${stop * 100}%`
            ).join(', ')})`
          }}
        />
        <p className="legend-scale">
          <span>{ramp.lowLabel}</span>
          <span>{ramp.highLabel}</span>
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
