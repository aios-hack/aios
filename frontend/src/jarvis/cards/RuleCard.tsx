import { DASH, formatNumber, formatPercent } from '../../ui/format';
import { useI18n } from '../../i18n/I18nContext';
import { readRule, readRuleSummary } from './cardPayloads';
import { EmptyPayload } from './EmptyPayload';
import type { RulePayload } from './payloadTypes';
import './RuleCard.css';

const RuleBody = ({ rule }: { rule: RulePayload }) => {
  const { lang, t } = useI18n();
  const inputs = Object.entries(rule.inputs);

  return (
    <div className="jarvis-rule">
      <p className="jarvis-rule-name">{rule.name}</p>
      <p className="jarvis-rule-statement">{rule.statement}</p>
      {inputs.length === 0 ? null : (
        <dl className="jarvis-rule-inputs">
          <dt className="jarvis-rule-inputs-label">{t('jarvis.ruleInputs')}</dt>
          {inputs.map(([key, value]) => (
            <dd className="jarvis-rule-input" key={key}>
              <span className="jarvis-rule-input-key">{key}</span>
              <span className="jarvis-rule-input-value">{formatNumber(lang, value, 3)}</span>
            </dd>
          ))}
        </dl>
      )}
      <p className="jarvis-rule-decision">
        <span className="jarvis-rule-decision-label">{t('jarvis.ruleDecision')}</span>
        <code className="jarvis-rule-decision-value">{rule.decision || DASH}</code>
      </p>
      <p className="jarvis-rule-impact">
        <span className="jarvis-rule-impact-label">{t('jarvis.ruleImpact')}</span>
        {rule.delta_npv === null ? (
          <span className="jarvis-rule-unmeasured">{t('jarvis.ruleUnmeasured')}</span>
        ) : (
          <span className="jarvis-rule-impact-value">
            {formatNumber(lang, rule.delta_npv)}
            {rule.share === null ? null : ` · ${formatPercent(lang, rule.share)}`}
          </span>
        )}
      </p>
    </div>
  );
};

export const RuleCard = ({ payload }: { payload: unknown }) => {
  const single = readRule(payload);
  if (single !== null) {
    return <RuleBody rule={single} />;
  }
  const summary = readRuleSummary(payload);
  if (summary === null) {
    return <EmptyPayload />;
  }
  return (
    <div className="jarvis-rule-list">
      {summary.rules.map((rule) => (
        <RuleBody key={rule.rule} rule={rule} />
      ))}
    </div>
  );
};
