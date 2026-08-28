import { memo, type CSSProperties } from 'react';
import type { Lang, Translate } from '../../i18n/I18nContext';
import { formatNumber, formatPercent } from '../../ui/format';
import type { AblationEntry } from './ablation';

interface AblationRowProps {
  entry: AblationEntry;
  index: number;
  ratio: number;
  name: string;
  statement: string;
  lang: Lang;
  t: Translate;
}

const reasonText = (t: Translate, reason: string): string => {
  const known = `npv.ablation.disabledReason.${reason}`;
  const text = t(known);
  return text === known ? t('npv.ablation.disabledReason.unknown', { reason }) : text;
};

const AblationRowView = ({
  entry,
  index,
  ratio,
  name,
  statement,
  lang,
  t
}: AblationRowProps) => {
  const measured = entry.delta !== null && entry.share !== null;

  return (
    <tr
      data-rule-id={entry.rule}
      data-state={entry.state}
      style={{ '--abl-row-index': index } as CSSProperties}
    >
      <th scope="row" className="abl-col-rule">
        <span className="abl-rule-code">{entry.rule}</span>
      </th>
      <td className="abl-col-name">
        <span className="abl-rule-name">{name}</span>
        {entry.state === 'disabled' && (
          <span className="abl-flag" data-on="false">
            {t('npv.ablation.flag.off')}
          </span>
        )}
      </td>
      <td className="abl-col-statement">
        <span className="abl-statement-text">{statement}</span>
        {entry.state === 'disabled' && entry.disabledReason !== null && (
          <span className="abl-reason">{reasonText(t, entry.disabledReason)}</span>
        )}
        {entry.state === 'zero' && (
          <span className="abl-reason">{t('npv.ablation.zeroHint')}</span>
        )}
      </td>
      <td className="abl-cell-delta" data-testid={`abl-delta-${entry.rule}`}>
        {!measured ? (
          <span className="abl-unmeasured">{t('npv.ablation.unmeasured')}</span>
        ) : entry.delta === 0 ? (
          <span className="abl-zero">{t('npv.ablation.zero')}</span>
        ) : (
          <span className="abl-delta">{formatNumber(lang, entry.delta as number)}</span>
        )}
      </td>
      <td className="abl-cell-share" data-testid={`abl-share-${entry.rule}`}>
        {!measured || entry.delta === 0 ? (
          <span className="abl-unmeasured" aria-hidden={entry.delta === 0}>
            {entry.delta === 0 ? '—' : t('npv.ablation.unmeasured')}
          </span>
        ) : (
          <span
            className="abl-contribution"
            title={t('npv.ablation.bar.title', {
              value: formatNumber(lang, entry.delta as number),
              share: formatPercent(lang, entry.share as number)
            })}
          >
            <span className="abl-share-value">
              {formatPercent(lang, entry.share as number)}
            </span>
            <span className="abl-bar-track">
              <span
                className="abl-bar"
                style={{ '--abl-bar-ratio': ratio } as CSSProperties}
              />
            </span>
          </span>
        )}
      </td>
    </tr>
  );
};

export const AblationRow = memo(AblationRowView);
