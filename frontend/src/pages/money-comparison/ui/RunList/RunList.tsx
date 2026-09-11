import type { RunRow } from '@/entities/runs/types';
import { useI18n } from '@/shared/i18n/I18nContext';
import { AskJarvis } from '@/features/ask-jarvis/ui';
import { DASH, formatNumber } from '@/shared/lib/format';
import './RunList.css';

const BILLION = 1e9;

const KNOWN_STATUSES = ['completed', 'running', 'failed'] as const;

export const statusKeyOf = (status: string): string | null =>
  (KNOWN_STATUSES as readonly string[]).includes(status)
    ? `npv.runs.status.${status}`
    : null;

export const npvOf = (row: RunRow): number | null => {
  const manifest = row.manifest;
  if (manifest === undefined) {
    return null;
  }
  if (typeof manifest.verified_npv === 'number' && Number.isFinite(manifest.verified_npv)) {
    return manifest.verified_npv;
  }
  if (typeof manifest.predicted_npv === 'number' && Number.isFinite(manifest.predicted_npv)) {
    return manifest.predicted_npv;
  }
  return null;
};

export const isVerified = (row: RunRow): boolean =>
  row.manifest !== undefined &&
  typeof row.manifest.verified_npv === 'number' &&
  Number.isFinite(row.manifest.verified_npv);

export const championOf = (rows: readonly RunRow[]): string | null => {
  let best: RunRow | null = null;
  let bestNpv = Number.NEGATIVE_INFINITY;
  for (const row of rows) {
    if (!isVerified(row) || row.manifest?.sound !== true) {
      continue;
    }
    const npv = npvOf(row);
    if (npv !== null && npv > bestNpv) {
      bestNpv = npv;
      best = row;
    }
  }
  return best?.run_id ?? null;
};

interface RunListProps {
  rows: readonly RunRow[];
  selected: string | null;
  onSelect: (runId: string) => void;
}

export const RunList = ({ rows, selected, onSelect }: RunListProps) => {
  const { t, lang } = useI18n();
  const champion = championOf(rows);

  return (
    <table className="run-list" data-testid="run-list">
      <caption className="run-list-caption">{t('npv.runs.title')}</caption>
      <thead>
        <tr>
          <th scope="col">{t('npv.runs.column.run')}</th>
          <th scope="col">{t('npv.runs.column.status')}</th>
          <th scope="col" className="numeric">
            {t('npv.runs.column.npv')}
          </th>
          <th scope="col">{t('npv.runs.column.provenance')}</th>
          <th scope="col">{t('npv.runs.column.submission')}</th>
          <th scope="col" />
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => {
          const npv = npvOf(row);
          return (
            <tr
              key={row.run_id}
              data-run={row.run_id}
              data-selected={selected === row.run_id}
              data-champion={champion === row.run_id}
            >
              <th scope="row">
                <button
                  type="button"
                  className="run-list-id"
                  onClick={() => onSelect(row.run_id)}
                >
                  {row.run_id}
                </button>
                {champion === row.run_id && (
                  <span className="run-list-champion" data-testid="run-list-champion">
                    {t('npv.runs.champion')}
                  </span>
                )}
              </th>
              <td data-status={row.status}>
                {(() => {
                  const key = statusKeyOf(row.status);
                  return key === null ? row.status : t(key);
                })()}
              </td>
              <td className="numeric">
                {npv === null ? DASH : formatNumber(lang, npv / BILLION, 3)}
              </td>
              <td>
                {t(
                  isVerified(row) ? 'npv.runs.provenance.opm' : 'npv.runs.provenance.surrogate'
                )}
              </td>
              <td>
                {row.manifest?.status === 'ready_to_submit'
                  ? t('npv.runs.submission.ready')
                  : DASH}
              </td>
              <td>
                <AskJarvis
                  question={t('askJarvis.run', { run: row.run_id })}
                  compact
                  testId={`ask-jarvis-run-${row.run_id}`}
                />
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
};
