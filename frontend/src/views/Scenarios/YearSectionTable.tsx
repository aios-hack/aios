import type { CSSProperties } from 'react';
import { useT } from '../../i18n/I18nContext';
import type { FieldError, YearRow, YearSection } from './constraints';

interface YearSectionTableProps {
  section: YearSection;
  index: number;
  rows: YearRow[];
  errors: FieldError[];
  onChange: (key: string, field: 'year' | 'value', value: string) => void;
  onAdd: () => void;
  onRemove: (key: string) => void;
}

const errorFor = (
  errors: FieldError[],
  key: string,
  field: string
): FieldError | undefined => errors.find((e) => e.key === key && e.field === field);

export const YearSectionTable = ({
  section,
  index,
  rows,
  errors,
  onChange,
  onAdd,
  onRemove
}: YearSectionTableProps) => {
  const t = useT();

  return (
    <section
      className="scenarios-section"
      data-section={section}
      data-empty={rows.length === 0}
      style={{ '--scenarios-section-index': index } as CSSProperties}
    >
      <header className="scenarios-section-head">
        <h4 className="scenarios-section-title">{t(`scenarios.section.${section}`)}</h4>
        <span className="scenarios-unit">{t(`scenarios.unit.${section}`)}</span>
      </header>
      {rows.length === 0 ? (
        <p className="inline-empty">{t('scenarios.section.empty')}</p>
      ) : (
        <table className="scenarios-table">
          <caption className="visually-hidden">{t(`scenarios.section.${section}`)}</caption>
          <thead>
            <tr>
              <th scope="col">{t('scenarios.column.year')}</th>
              <th scope="col">{t(`scenarios.column.value.${section}`)}</th>
              <th scope="col">
                <span className="scenarios-visually-hidden">
                  {t('scenarios.column.actions')}
                </span>
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const yearError = errorFor(errors, row.key, 'year');
              const valueError = errorFor(errors, row.key, 'value');
              return (
                <tr key={row.key} data-row-key={row.key}>
                  <td>
                    <input
                      className="scenarios-input"
                      type="text"
                      inputMode="numeric"
                      value={row.year}
                      aria-label={`${t(`scenarios.section.${section}`)} — ${t('scenarios.column.year')}`}
                      aria-invalid={yearError !== undefined}
                      onChange={(event) => onChange(row.key, 'year', event.target.value)}
                    />
                    {yearError && (
                      <p className="scenarios-field-error" role="alert">
                        {t(`scenarios.${yearError.messageKey}`, yearError.params)}
                      </p>
                    )}
                  </td>
                  <td>
                    <input
                      className="scenarios-input"
                      type="text"
                      inputMode="decimal"
                      value={row.value}
                      aria-label={`${t(`scenarios.section.${section}`)} — ${t(`scenarios.column.value.${section}`)}`}
                      aria-invalid={valueError !== undefined}
                      onChange={(event) => onChange(row.key, 'value', event.target.value)}
                    />
                    {valueError && (
                      <p className="scenarios-field-error" role="alert">
                        {t(`scenarios.${valueError.messageKey}`, valueError.params)}
                      </p>
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
        {t('scenarios.action.addRow')}
      </button>
    </section>
  );
};
