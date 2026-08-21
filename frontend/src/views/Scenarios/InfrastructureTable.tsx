import { useT } from '../../i18n/I18nContext';
import type { FieldError, PairRow } from './constraints';

interface InfrastructureTableProps {
  rows: PairRow[];
  errors: FieldError[];
  onChange: (key: string, field: 'name' | 'value', value: string) => void;
  onAdd: () => void;
  onRemove: (key: string) => void;
}

export const InfrastructureTable = ({
  rows,
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
    >
      <header className="scenarios-section-head">
        <h4 className="scenarios-section-title">{t('scenarios.section.infrastructure')}</h4>
        <span className="scenarios-unit">{t('scenarios.unit.infrastructure')}</span>
      </header>
      {rows.length === 0 ? (
        <p className="scenarios-empty">{t('scenarios.section.empty')}</p>
      ) : (
        <table className="scenarios-table">
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
              const nameError = errors.find((e) => e.key === row.key && e.field === 'name');
              return (
                <tr key={row.key} data-row-key={row.key}>
                  <td>
                    <input
                      className="scenarios-input"
                      type="text"
                      value={row.name}
                      aria-label={t('scenarios.column.pairName')}
                      aria-invalid={nameError !== undefined}
                      onChange={(event) => onChange(row.key, 'name', event.target.value)}
                    />
                    {nameError && (
                      <p className="scenarios-field-error" role="alert">
                        {t(`scenarios.${nameError.messageKey}`, nameError.params)}
                      </p>
                    )}
                  </td>
                  <td>
                    <input
                      className="scenarios-input"
                      type="text"
                      value={row.value}
                      aria-label={t('scenarios.column.pairValue')}
                      onChange={(event) => onChange(row.key, 'value', event.target.value)}
                    />
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
