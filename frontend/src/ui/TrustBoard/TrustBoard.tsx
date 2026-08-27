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
  const full = renderValue(t, lang, indicator);
  const detail =
    indicator.detailKey === undefined
      ? null
      : t(indicator.detailKey, localizeParams(lang, indicator.detailParams));
  const brief =
    indicator.briefKey === undefined
      ? full
      : t(indicator.briefKey, localizeParams(lang, indicator.briefParams));
  const parts = [full, detail].filter(
    (part): part is string => typeof part === 'string' && part !== brief
  );
  const extra = parts.length === 0 ? null : parts.join(' · ');

  return (
    <li
      className="trust-item"
      data-indicator={indicator.id}
      data-status={indicator.status}
      title={extra ?? undefined}
    >
      <span className="trust-label">{t(indicator.labelKey)}</span>
      <span className="trust-value">{brief}</span>
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

  const indicators = buildIndicators(active, source);
  const byId = (id: string) => indicators.find((indicator) => indicator.id === id);
  const groups: { key: string; ids: string[] }[] = [
    { key: 'source', ids: ['number', 'provenance'] },
    { key: 'checks', ids: ['converged', 'selfConsistent', 'domain'] },
    { key: 'risk', ids: ['regret'] }
  ];
  const estimate = byId('number')?.status === 'unmeasured';
  const failed = indicators.filter((indicator) => indicator.status === 'danger');

  return (
    <section className="trust-board" aria-label={t('trust.title')} data-testid="trust-board">
      <header className="trust-board-head">
        <h2 className="trust-board-title">{t('trust.title')}</h2>
      </header>
      {groups.map((group) => {
        const rows = group.ids.map(byId).filter((row): row is TrustIndicator => row !== undefined);
        if (rows.length === 0) {
          return null;
        }
        return (
          <div className="trust-group" key={group.key}>
            <h3 className="trust-group-title">{t(`trust.group.${group.key}`)}</h3>
            <ul className="trust-list">
              {rows.map((indicator) => (
                <Row key={indicator.id} indicator={indicator} />
              ))}
            </ul>
          </div>
        );
      })}
      <footer className="trust-board-foot" data-tone={failed.length > 0 || estimate ? 'warn' : 'ok'}>
        {failed.length > 0
          ? t(failed[0].valueKey)
          : t(estimate ? 'trust.flaggedOne' : 'trust.allClear')}
      </footer>
    </section>
  );
};
