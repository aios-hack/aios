import { useT } from '../../i18n/I18nContext';
import type { FieldError, OutageRow } from './constraints';

interface OutageTableProps {
  rows: OutageRow[];
  errors: FieldError[];
  nIntervals: number;
  onChange: (key: string, field: 'well' | 'from' | 'to', value: string) => void;
  onAdd: () => void;
  onRemove: (key: string) => void;
}

const FIELDS: ('well' | 'from' | 'to')[] = ['well', 'from', 'to'];

export const OutageTable = ({
  rows,
  errors,
  nIntervals,
  onChange,
  onAdd,
  onRemove
}: OutageTableProps) => {
  const t = useT();

  return (
    <section className="scenarios-section" data-section="well_outages">
      <header className="scenarios-section-head">
        <h4 className="scenarios-section-title">{t('scenarios.section.well_outages')}</h4>
        <span className="scenarios-unit">
          {t('scenarios.unit.well_outages', { last: nIntervals - 1 })}
        </span>
      </header>
      {rows.length === 0 ? (
        <p className="scenarios-empty">{t('scenarios.section.empty')}</p>
      ) : (
        <table className="scenarios-table">
          <thead>
            <tr>
              <th scope="col">{t('scenarios.column.well')}</th>
              <th scope="col">{t('scenarios.column.stepFrom')}</th>
              <th scope="col">{t('scenarios.column.stepTo')}</th>
              <th scope="col">
                <span className="scenarios-visually-hidden">
                  {t('scenarios.column.actions')}
                </span>
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.key} data-row-key={row.key}>
                {FIELDS.map((field) => {
                  const error = errors.find((e) => e.key === row.key && e.field === field);
                  const label =
                    field === 'well'
                      ? t('scenarios.column.well')
                      : field === 'from'
                        ? t('scenarios.column.stepFrom')
                        : t('scenarios.column.stepTo');
                  return (
                    <td key={field}>
                      <input
                        className="scenarios-input"
                        type="text"
                        inputMode={field === 'well' ? 'text' : 'numeric'}
                        value={row[field]}
                        aria-label={`${t('scenarios.section.well_outages')} — ${label}`}
                        aria-invalid={error !== undefined}
                        onChange={(event) => onChange(row.key, field, event.target.value)}
                      />
                      {error && (
                        <p className="scenarios-field-error" role="alert">
                          {t(`scenarios.${error.messageKey}`, error.params)}
                        </p>
                      )}
                    </td>
                  );
                })}
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
            ))}
          </tbody>
        </table>
      )}
      <button type="button" className="scenarios-add-button" onClick={onAdd}>
        {t('scenarios.action.addOutage')}
      </button>
    </section>
  );
};
