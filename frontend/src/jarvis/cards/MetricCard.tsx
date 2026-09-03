import { Sparkline } from '../../ui/Sparkline';
import { DASH, formatNumber } from '../../ui/format';
import { useI18n } from '../../i18n/I18nContext';
import { readMetrics } from './cardPayloads';
import { EmptyPayload } from './EmptyPayload';
import type { MetricPayload } from './payloadTypes';
import './MetricCard.css';

const MetricRow = ({ metric }: { metric: MetricPayload }) => {
  const { lang, t } = useI18n();
  const values = metric.spark.map((point) => point.value);

  return (
    <div className="jarvis-metric-row">
      <p className="jarvis-metric-label">{metric.label}</p>
      <p className="jarvis-metric-value">
        <span className="jarvis-metric-number">{formatNumber(lang, metric.value)}</span>
        <span className="jarvis-metric-unit">{metric.unit}</span>
      </p>
      {metric.delta === null || metric.delta === 0 ? null : (
        <p className="jarvis-metric-delta" data-sign={metric.delta >= 0 ? 'up' : 'down'}>
          <span className="jarvis-metric-delta-label">{t('jarvis.metricDelta')}</span>
          {formatNumber(lang, metric.delta)}
        </p>
      )}
      {values.length === 0 ? (
        <p className="jarvis-metric-nospark">{DASH}</p>
      ) : (
        <Sparkline
          values={values}
          current={values.length - 1}
          label={metric.label}
          stroke="var(--color-jarvis-body)"
          height={36}
        />
      )}
    </div>
  );
};

export const MetricCard = ({ payload }: { payload: unknown }) => {
  const metrics = readMetrics(payload);
  if (metrics.length === 0) {
    return <EmptyPayload />;
  }

  return (
    <div className="jarvis-metric">
      {metrics.map((metric) => (
        <MetricRow key={metric.id} metric={metric} />
      ))}
    </div>
  );
};
