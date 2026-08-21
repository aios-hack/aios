import { useI18n } from '../../i18n/I18nContext';
import { DASH, formatNumber } from '../../ui/format';
import { dimState, type CouncilPath, type WellRow } from './levels';

interface WellLevelProps {
  rows: readonly WellRow[];
  groupLabel: string;
  path: CouncilPath | null;
  onSelectWell: (well: string) => void;
}

const InputsCell = ({ inputs }: { inputs: Record<string, number> }) => {
  const { t, lang } = useI18n();
  const entries = Object.entries(inputs);
  if (entries.length === 0) {
    return <span className="council-muted">{DASH}</span>;
  }
  return (
    <span className="council-inputs">
      {entries.map(([key, value]) => (
        <span key={key} className="council-input">
          <span className="council-muted">{t(`council.input.${key}`)}</span>
          <span className="council-number">{formatNumber(lang, value, 2)}</span>
        </span>
      ))}
    </span>
  );
};

export const WellLevel = ({ rows, groupLabel, path, onSelectWell }: WellLevelProps) => {
  const { t } = useI18n();

  return (
    <section className="council-level" data-level="wells" data-testid="council-wells">
      <h3 className="council-level-title">
        {t('council.wells.title', { group: groupLabel })}
      </h3>
      {rows.length === 0 ? (
        <p className="council-empty">{t('council.wells.empty')}</p>
      ) : (
        <table className="council-table">
          <thead>
            <tr>
              <th scope="col">{t('council.wells.well')}</th>
              <th scope="col">{t('council.wells.decision')}</th>
              <th scope="col">{t('council.wells.rule')}</th>
              <th scope="col">{t('council.wells.inputs')}</th>
              <th scope="col">{t('council.wells.constraint')}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={row.well}
                data-testid={`council-well-${row.well}`}
                data-state={dimState(path, path?.well === row.well)}
              >
                <th scope="row">
                  <button
                    type="button"
                    className="council-well-button"
                    onClick={() => onSelectWell(row.well)}
                  >
                    {row.color !== null && (
                      <span className="council-swatch" style={{ background: row.color }} />
                    )}
                    <span className="council-number">{row.well}</span>
                  </button>
                </th>
                <td className="council-number">{row.decision}</td>
                <td>
                  <span className="council-rule" title={t(`council.rule.${row.rule}`)}>
                    {row.rule}
                  </span>
                </td>
                <td>
                  <InputsCell inputs={row.inputs} />
                </td>
                <td>
                  {row.constraint === null ? (
                    <span className="council-muted">{t('council.wells.noConstraint')}</span>
                  ) : (
                    <span className="council-constraint" data-testid={`council-constraint-${row.well}`}>
                      {t(`council.constraint.${row.constraint}`)}
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
};
