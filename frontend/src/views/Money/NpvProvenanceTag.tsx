import { useI18n } from '../../i18n/I18nContext';
import { formatNumber } from '../../ui/format';
import type { NpvProvenance } from './provenance';
import './NpvProvenanceTag.css';

interface NpvProvenanceTagProps {
  provenance: NpvProvenance;
  scenarioId: string;
  testId?: string;
}

export const NpvProvenanceTag = ({
  provenance,
  scenarioId,
  testId
}: NpvProvenanceTagProps) => {
  const { t, lang } = useI18n();
  const money = (value: string | number): string =>
    typeof value === 'number' ? formatNumber(lang, value) : value;

  const label = t(
    provenance.labelKey,
    provenance.params === undefined
      ? undefined
      : Object.fromEntries(
          Object.entries(provenance.params).map(([key, value]) => [
            key,
            key === 'run' ? String(value) : money(value)
          ])
        )
  );

  const note =
    provenance.noteKey === undefined
      ? null
      : t(
          provenance.noteKey,
          provenance.noteParams === undefined
            ? undefined
            : Object.fromEntries(
                Object.entries(provenance.noteParams).map(([key, value]) => [
                  key,
                  key === 'predicted'
                    ? money(value)
                    : typeof value === 'number'
                      ? formatNumber(lang, value, 2)
                      : value
                ])
              )
        );

  return (
    <span
      className="npv-provenance"
      data-kind={provenance.kind}
      data-testid={testId ?? `npv-provenance-${scenarioId}`}
    >
      <span className="npv-provenance-label">{label}</span>
      {note !== null && <span className="npv-provenance-note">{note}</span>}
      {provenance.synthetic && (
        <span className="npv-provenance-note" data-testid={`npv-synthetic-${scenarioId}`}>
          {t('npv.provenance.synthetic')}
        </span>
      )}
    </span>
  );
};
