import { useT } from '../../i18n/I18nContext';

interface ShownCounterProps {
  shown: number;
  total: number;
}

export const ShownCounter = ({ shown, total }: ShownCounterProps) => {
  const t = useT();
  const ratio = total > 0 ? shown / total : 0;

  return (
    <div
      className="shown-counter"
      role="status"
      aria-label={t('map.shown', { shown, total })}
    >
      <span className="shown-counter-label">{t('map.shownLabel')}</span>
      <span className="shown-counter-values">
        <span className="shown-counter-current">{shown}</span>
        <span className="shown-counter-total">/ {total}</span>
      </span>
      <span className="shown-counter-track" aria-hidden="true">
        <span
          className="shown-counter-fill"
          style={{ transform: `scaleX(${ratio})` }}
        />
      </span>
    </div>
  );
};
