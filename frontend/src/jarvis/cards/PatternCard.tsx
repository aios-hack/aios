import { formatNumber } from '../../ui/format';
import { useI18n } from '../../i18n/I18nContext';
import { readPattern } from './cardPayloads';
import { EmptyPayload } from './EmptyPayload';
import './PatternCard.css';

export const PatternCard = ({ payload }: { payload: unknown }) => {
  const { lang, t } = useI18n();
  const pattern = readPattern(payload);
  if (pattern === null) {
    return <EmptyPayload />;
  }
  const inputs = Object.entries(pattern.inputs);

  return (
    <div className="jarvis-pattern">
      <p className="jarvis-pattern-name">{pattern.name}</p>
      <p className="jarvis-pattern-meta">
        <span className="jarvis-pattern-well">{pattern.well}</span>
        <span className="jarvis-pattern-severity" data-severity={pattern.severity}>
          {t('jarvis.patternSeverity')}: {pattern.severity}
        </span>
      </p>
      <p className="jarvis-pattern-window">
        {t('jarvis.patternWindow')} {pattern.window.from_step}–{pattern.window.to_step}
      </p>
      {inputs.length === 0 ? null : (
        <dl className="jarvis-pattern-inputs">
          {inputs.map(([key, value]) => (
            <div key={key}>
              <dt>{key}</dt>
              <dd>{formatNumber(lang, value, 3)}</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
};
