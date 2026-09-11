import type { Translate } from '@/shared/i18n/I18nContext';
import type { Lang } from '@/shared/i18n/dictionaries';
import { ProvenanceValue } from '@/pages/money-constraints/ui/ProvenanceValue';

interface ProvenanceRowsProps {
  fields: readonly string[];
  source: Record<string, unknown>;
  lang: Lang;
  t: Translate;
}

export const ProvenanceRows = ({ fields, source, lang, t }: ProvenanceRowsProps) => (
  <dl className="run-provenance-list">
    {fields.map((name) => (
      <div className="run-provenance-row" key={name}>
        <dt>{t(`runs.field.${name}`)}</dt>
        <dd>
          <ProvenanceValue name={name} value={source[name]} lang={lang} t={t} />
        </dd>
      </div>
    ))}
  </dl>
);
