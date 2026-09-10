import type { ComparisonFile, ComparisonSideFile } from '../../api/types';
import { useI18n } from '../../i18n/I18nContext';
import { DASH, formatNumber } from '../../ui/format';
import './RunList.css';

const BILLION = 1e9;

const countOf = (value: number | null | undefined): string =>
  typeof value === 'number' && Number.isFinite(value) ? String(value) : DASH;

interface Row {
  key: string;
  label: string;
  baseline: string;
  candidate: string;
  delta: string;
}

export const buildRows = (
  file: ComparisonFile,
  label: (key: string) => string,
  number: (value: number, digits: number) => string
): Row[] => {
  const side = (item: ComparisonSideFile): ComparisonSideFile => item;
  const base = side(file.baseline);
  const cand = side(file.candidate);
  const delta = file.delta;
  return [
    {
      key: 'npv',
      label: label('npv.compare.row.npv'),
      baseline: number(base.npv_rub / BILLION, 3),
      candidate: number(cand.npv_rub / BILLION, 3),
      delta: number(delta.npv_rub / BILLION, 3)
    },
    {
      key: 'percent',
      label: label('npv.compare.row.percent'),
      baseline: DASH,
      candidate: number(delta.npv_percent, 2),
      delta: DASH
    },
    {
      key: 'blocking',
      label: label('npv.compare.row.blocking'),
      baseline: countOf(base.violations.blocking),
      candidate: countOf(cand.violations.blocking),
      delta: countOf(delta.blocking_violations)
    },
    {
      key: 'dynamic',
      label: label('npv.compare.row.dynamic'),
      baseline: countOf(base.violations.dynamic),
      candidate: countOf(cand.violations.dynamic),
      delta: DASH
    },
    {
      key: 'sound',
      label: label('npv.compare.row.sound'),
      baseline: label(base.sound ? 'npv.compare.yes' : 'npv.compare.no'),
      candidate: label(cand.sound ? 'npv.compare.yes' : 'npv.compare.no'),
      delta: DASH
    },
    {
      key: 'wallclock',
      label: label('npv.compare.row.wallclock'),
      baseline: number(base.wallclock_seconds, 1),
      candidate: number(cand.wallclock_seconds, 1),
      delta: number(delta.wallclock_seconds, 1)
    },
    {
      key: 'opm',
      label: label('npv.compare.row.opmRuns'),
      baseline: String(base.opm_runs),
      candidate: String(cand.opm_runs),
      delta: String(base.opm_runs + cand.opm_runs)
    }
  ];
};

export const BaselineTable = ({ file }: { file: ComparisonFile }) => {
  const { t, lang } = useI18n();
  const rows = buildRows(file, t, (value, digits) => formatNumber(lang, value, digits));

  return (
    <section className="run-compare" data-testid="run-compare">
      <table className="run-list">
        <caption className="run-list-caption">
          {t('npv.compare.title', { run: file.run_id })}
        </caption>
        <thead>
          <tr>
            <th scope="col">{t('npv.compare.column.metric')}</th>
            <th scope="col" className="numeric">
              {t('npv.compare.column.baseline')}
            </th>
            <th scope="col" className="numeric">
              {t('npv.compare.column.candidate')}
            </th>
            <th scope="col" className="numeric">
              {t('npv.compare.column.delta')}
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.key} data-row={row.key}>
              <th scope="row">{row.label}</th>
              <td className="numeric">{row.baseline}</td>
              <td className="numeric">{row.candidate}</td>
              <td className="numeric">{row.delta}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="run-compare-conditions" data-testid="run-compare-conditions">
        {t('npv.compare.conditions', {
          image: file.conditions.opm_image,
          deck: file.conditions.deck_hash.slice(0, 12)
        })}
      </p>
    </section>
  );
};
