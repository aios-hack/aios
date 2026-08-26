import { useDataset } from '../../data';
import { useI18n, type Lang, type Translate } from '../../i18n/I18nContext';
import { DEFAULT_SCENARIO_ID, useOptionalScenario } from '../../state/ScenarioContext';
import { useProvenance } from '../../state/ProvenanceContext';
import { formatNumber } from '../format';
import { buildIndicators, type TrustIndicator } from './indicators';
import './TrustBoard.css';

const MONEY_KEYS = ['value'];

const localizeParams = (
  lang: Lang,
  params: Record<string, string | number> | undefined
): Record<string, string | number> | undefined => {
  if (!params) {
    return undefined;
  }
  return Object.fromEntries(
    Object.entries(params).map(([key, value]) => [
      key,
      typeof value === 'number'
        ? formatNumber(lang, value, MONEY_KEYS.includes(key) ? 0 : 2)
        : value
    ])
  );
};

const renderValue = (
  t: Translate,
  lang: Lang,
  indicator: TrustIndicator
): string => t(indicator.valueKey, localizeParams(lang, indicator.valueParams));

const Row = ({ indicator }: { indicator: TrustIndicator }) => {
  const { t, lang } = useI18n();
  const detail =
    indicator.detailKey === undefined
      ? null
      : t(indicator.detailKey, localizeParams(lang, indicator.detailParams));
  const value = renderValue(t, lang, indicator);
  const collapsed =
    indicator.banner !== true &&
    indicator.spoken !== true &&
    indicator.briefKey !== undefined;
  const brief = collapsed
    ? t(indicator.briefKey as string, localizeParams(lang, indicator.briefParams))
    : null;

  return (
    <li
      className="trust-item"
      data-indicator={indicator.id}
      data-status={indicator.status}
      data-collapsed={collapsed ? 'true' : undefined}
      data-full={collapsed ? [value, detail].filter(Boolean).join(' · ') : undefined}
      tabIndex={collapsed ? 0 : undefined}
    >
      <span className="trust-dot" aria-hidden="true" />
      <span className="trust-label">{t(indicator.labelKey)}</span>
      {brief !== null && (
        <span className="trust-brief" aria-hidden="true">
          {brief}
        </span>
      )}
      <span className="trust-value">{value}</span>
      {detail !== null && <span className="trust-detail">{detail}</span>}
    </li>
  );
};

const Notice = ({ textKey }: { textKey: string }) => {
  const { t } = useI18n();
  return (
    <p className="trust-board-notice" data-testid="trust-board-notice">
      {t(textKey)}
    </p>
  );
};

export const TrustBoard = () => {
  const { t } = useI18n();
  const { activeId } = useOptionalScenario();
  const source = useProvenance();
  const index = useDataset('scenarios');

  if (index.status === 'loading') {
    return <Notice textKey="trust.index.loading" />;
  }
  if (index.status !== 'ready') {
    return <Notice textKey="trust.index.error" />;
  }

  const entries = index.data.scenarios;
  const active =
    entries.find((entry) => entry.id === activeId) ??
    (activeId === DEFAULT_SCENARIO_ID ? entries[0] : undefined);

  if (!active) {
    return <Notice textKey="trust.index.missing" />;
  }

  return (
    <section className="trust-board" aria-label={t('trust.title')} data-testid="trust-board">
      <ul className="trust-list">
        {buildIndicators(active, source).map((indicator) => (
          <Row key={indicator.id} indicator={indicator} />
        ))}
      </ul>
    </section>
  );
};
