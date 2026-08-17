import './CountMeter.css';

interface CountMeterProps {
  label: string;
  shown: number;
  total: number;
  ariaLabel: string;
  bar?: boolean;
}

export const CountMeter = ({
  label,
  shown,
  total,
  ariaLabel,
  bar = true
}: CountMeterProps) => {
  const ratio = total > 0 ? shown / total : 0;

  return (
    <div className="count-meter" role="status" aria-label={ariaLabel}>
      <span className="count-meter-label">{label}</span>
      <span className="count-meter-values">
        <span className="count-meter-current">{shown}</span>
        <span className="count-meter-total">/ {total}</span>
      </span>
      {bar && (
        <span className="count-meter-track" aria-hidden="true">
          <span className="count-meter-fill" style={{ transform: `scaleX(${ratio})` }} />
        </span>
      )}
    </div>
  );
};
