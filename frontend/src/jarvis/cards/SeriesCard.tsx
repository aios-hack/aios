import { Sparkline } from '../../ui/Sparkline';
import { DASH, formatNumber, formatStepDate } from '../../ui/format';
import { useI18n } from '../../i18n/I18nContext';
import { readSeries } from './cardPayloads';
import { EmptyPayload } from './EmptyPayload';
import './SeriesCard.css';

export const windowShare = (
  from: number,
  to: number,
  first: number,
  last: number
): { start: number; width: number } | null => {
  const span = last - first;
  if (span <= 0) {
    return null;
  }
  const start = Math.min(Math.max((from - first) / span, 0), 1);
  const end = Math.min(Math.max((to - first) / span, 0), 1);
  if (end <= start) {
    return null;
  }
  return { start, width: end - start };
};

export const SeriesCard = ({ payload }: { payload: unknown }) => {
  const { lang, t } = useI18n();
  const series = readSeries(payload);
  if (series === null) {
    return <EmptyPayload />;
  }
  const values = series.rows.map((row) => row.value);
  const first = series.rows[0];
  const last = series.rows[series.rows.length - 1];
  const highlight =
    series.window === null
      ? null
      : windowShare(series.window[0], series.window[1], first.step, last.step);

  return (
    <div className="jarvis-series">
      <div className="jarvis-series-plot">
        {highlight === null ? null : (
          <span
            className="jarvis-series-window"
            aria-hidden="true"
            style={{
              insetInlineStart: `${highlight.start * 100}%`,
              inlineSize: `${highlight.width * 100}%`
            }}
          />
        )}
        <Sparkline
          values={values}
          current={values.length - 1}
          label={series.metric}
          stroke="var(--color-jarvis-body)"
          height={64}
        />
      </div>
      <p className="jarvis-series-axis">
        <span>{formatStepDate(lang, first.date)}</span>
        <span className="jarvis-series-unit">{series.unit}</span>
        <span>{formatStepDate(lang, last.date)}</span>
      </p>
      <p className="jarvis-series-last">
        {last.value === null ? DASH : formatNumber(lang, last.value, 2)}
        {series.window === null ? null : (
          <span className="jarvis-series-window-label">
            {t('jarvis.seriesWindow')} {series.window[0]}–{series.window[1]}
          </span>
        )}
      </p>
    </div>
  );
};
