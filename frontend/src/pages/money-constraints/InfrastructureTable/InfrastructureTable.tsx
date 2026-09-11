import type { CSSProperties } from 'react';
import { INFRASTRUCTURE_PARAMETERS } from '@/pages/money-constraints/infrastructureParameters';
import { useT } from '@/shared/i18n/I18nContext';
import type { FieldError, PairRow } from '@/pages/money-constraints/constraints';

interface InfrastructureTableProps {
  rows: PairRow[];
  index: number;
  errors: FieldError[];
  onChange: (key: string, field: 'name' | 'value', value: string) => void;
  onAdd: () => void;
  onRemove: (key: string) => void;
}

export const InfrastructureTable = ({
  rows,
  index,
  errors,
  onChange,
  onAdd,
  onRemove
}: InfrastructureTableProps) => {
  const t = useT();

  return (
    <section
      className="scenarios-section"
      data-section="infrastructure"
      data-empty={rows.length === 0}
      style={{ '--scenarios-section-index': index } as CSSProperties}
    >
      <header className="scenarios-section-head">
        <h4 className="scenarios-section-title">{t('scenarios.section.infrastructure')}</h4>
        <span className="scenarios-unit">{t('scenarios.unit.infrastructure')}</span>
      </header>
      {rows.length === 0 ? (
        <p className="inline-empty">{t('scenarios.section.empty')}</p>
      ) : (
        <table className="scenarios-table">
          <caption className="visually-hidden">{t('scenarios.section.infrastructure')}</caption>
          <thead>
            <tr>
              <th scope="col">{t('scenarios.column.pairName')}</th>
              <th scope="col">{t('scenarios.column.pairValue')}</th>
              <th scope="col">
                <span className="scenarios-visually-hidden">
                  {t('scenarios.column.actions')}
                </span>
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const nameError = errors.find((e) => e.key === row.key);
              const parameter = INFRASTRUCTURE_PARAMETERS.find((p) => p.key === row.name);
              return (
                <tr key={row.key} data-row-key={row.key}>
                  <td>
                    <select
                      className="scenarios-input"
                      value={row.name}
                      aria-label={t('scenarios.column.pairName')}
                      aria-invalid={nameError !== undefined}
                      onChange={(event) => onChange(row.key, 'name', event.target.value)}
                    >
                      <option value="">{t('scenarios.parameter.choose')}</option>
                      {row.name && !parameter && <option value={row.name}>{t('scenarios.parameter.unknown')}</option>}
                      {INFRASTRUCTURE_PARAMETERS.map((p) => (
                        <option key={p.key} value={p.key} disabled={rows.some((other) => other.key !== row.key && other.name === p.key)}>
                          {t(`scenarios.parameter.${p.key}.label`)}
                        </option>
                      ))}
                    </select>
                    {parameter && <p className="scenarios-note">{t(`scenarios.parameter.${parameter.key}.hint`)}</p>}
                    {nameError && (
                      <p className="scenarios-field-error" role="alert">
                        {t(`scenarios.${nameError.messageKey}`, nameError.params)}
                      </p>
                    )}
                  </td>
                  <td>
                    {parameter && 'choices' in parameter ? (
                      <select className="scenarios-input" value={row.value}
                        aria-label={t('scenarios.column.pairValue')}
                        onChange={(event) => onChange(row.key, 'value', event.target.value)}>
                        <option value="">{t('scenarios.parameter.choose')}</option>
                        {parameter.choices.map((choice) => <option key={choice} value={choice}>{t(`scenarios.parameter.${choice}`)}</option>)}
                      </select>
                    ) : (
                      <input className="scenarios-input" type="text" inputMode="decimal"
                        value={row.value} aria-label={t('scenarios.column.pairValue')}
                        onChange={(event) => onChange(row.key, 'value', event.target.value)} />
                    )}
                  </td>
                  <td className="scenarios-cell-action">
                    <button
                      type="button"
                      className="scenarios-row-button"
                      onClick={() => onRemove(row.key)}
                    >
                      {t('scenarios.action.removeRow')}
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      <button type="button" className="scenarios-add-button" onClick={onAdd}>
        {t('scenarios.action.addPair')}
      </button>
    </section>
  );
};
