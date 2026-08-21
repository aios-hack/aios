import { memo, type CSSProperties } from 'react';
import type { Lang, Translate } from '../../i18n/I18nContext';
import { formatNumber, formatPercent } from '../../ui/format';
import { barRatio, type AblationEntry } from './ablation';

interface AblationRowProps {
  entry: AblationEntry;
  lang: Lang;
  t: Translate;
}

const reasonText = (t: Translate, reason: string): string => {
  const known = `npv.ablation.disabledReason.${reason}`;
  const text = t(known);
  return text === known ? t('npv.ablation.disabledReason.unknown', { reason }) : text;
};

const AblationRowView = ({ entry, lang, t }: AblationRowProps) => {
  const ratio = barRatio(entry.share);
  const known = t(`npv.ablation.rule.${entry.rule}.name`);
  const name = known === `npv.ablation.rule.${entry.rule}.name` ? entry.rule : known;
  const statement = t(`npv.ablation.rule.${entry.rule}.statement`);

  return (
    <tr data-rule-id={entry.rule} data-state={entry.state}>
      <th scope="row">
        <span className="abl-rule-code">{entry.rule}</span>
        <span className="abl-rule-name">{name}</span>
      </th>
      <td className="abl-statement">
        <span>{statement === `npv.ablation.rule.${entry.rule}.statement` ? '' : statement}</span>
        {entry.state === 'disabled' && entry.disabledReason !== null && (
          <span className="abl-reason">{reasonText(t, entry.disabledReason)}</span>
        )}
        {entry.state === 'zero' && (
          <span className="abl-reason">{t('npv.ablation.zeroHint')}</span>
        )}
      </td>
      <td>
        <span className="abl-flag" data-on={entry.state !== 'disabled'}>
          {t(entry.state === 'disabled' ? 'npv.ablation.flag.off' : 'npv.ablation.flag.on')}
        </span>
      </td>
      <td className="abl-cell-num" data-testid={`abl-delta-${entry.rule}`}>
        {entry.delta === null ? (
          <span className="abl-unmeasured">{t('npv.ablation.unmeasured')}</span>
        ) : entry.delta === 0 ? (
          <span className="abl-zero">{t('npv.ablation.zero')}</span>
        ) : (
          formatNumber(lang, entry.delta)
        )}
      </td>
      <td className="abl-cell-bar" data-testid={`abl-share-${entry.rule}`}>
        {ratio === null || entry.share === null ? (
          <span className="abl-unmeasured">{t('npv.ablation.unmeasured')}</span>
        ) : (
          <span className="abl-share">
            <span className="abl-bar-track">
              <span
                className="abl-bar"
                style={{ '--abl-bar-ratio': ratio } as CSSProperties}
              />
            </span>
            <span className="abl-share-value">{formatPercent(lang, entry.share)}</span>
          </span>
        )}
      </td>
    </tr>
  );
};

export const AblationRow = memo(AblationRowView);
