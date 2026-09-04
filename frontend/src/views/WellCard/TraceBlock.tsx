import type { TraceRecord } from '../../api/types';
import { useI18n } from '../../i18n/I18nContext';
import { ExplainButton } from '../../jarvis/actions/ExplainButton';
import { formatNumber } from '../../ui/format';
import './TraceBlock.css';

interface TraceBlockProps {
  records: TraceRecord[];
  well: string;
  step: number;
}

export const TraceBlock = ({ records, well, step }: TraceBlockProps) => {
  const { t, lang } = useI18n();

  if (records.length === 0) {
    return (
      <div className="wellcard-trace-empty">
        <p className="wellcard-empty">{t('wellcard.decision.empty')}</p>
        <ExplainButton well={well} step={step} />
      </div>
    );
  }

  return (
    <ol className="wellcard-trace" data-guide="rules-trace">
      <li className="wellcard-trace-actions">
        <ExplainButton well={well} step={step} />
      </li>
      {records.map((record, index) => (
        <li key={`${record.rule}-${index}`} className="wellcard-trace-item">
          <div className="wellcard-trace-head">
            <span className="wellcard-rule">{record.rule}</span>
            <span className="wellcard-decision">{record.decision}</span>
          </div>
          <table className="wellcard-inputs">
            <caption className="visually-hidden">
              {t('wellcard.decision.inputsCaption', { rule: record.rule })}
            </caption>
            <thead>
              <tr>
                <th scope="col">{t('wellcard.decision.inputName')}</th>
                <th scope="col">{t('wellcard.decision.inputValue')}</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(record.inputs).map(([name, value]) => (
                <tr key={name}>
                  <th scope="row">{name}</th>
                  <td>{formatNumber(lang, value, 3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </li>
      ))}
    </ol>
  );
};
