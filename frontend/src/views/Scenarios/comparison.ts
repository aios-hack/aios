import type { NpvFile, ScenarioEntry } from '../../api/types';
import type { TaxMode } from '../NpvRank/types';

export interface ScenarioTotals {
  preTax: number;
  withTax: number;
}

export interface ScenarioComparison {
  baseId: string;
  otherId: string;
  base: ScenarioTotals;
  other: ScenarioTotals;
  delta: ScenarioTotals;
}

export const totalsOf = (file: NpvFile): ScenarioTotals => ({
  preTax: file.total.pre_tax,
  withTax: file.total.with_allocated_tax
});

export const valueFor = (totals: ScenarioTotals, mode: TaxMode): number =>
  mode === 'preTax' ? totals.preTax : totals.withTax;

export const compareScenarios = (
  baseId: string,
  otherId: string,
  base: NpvFile,
  other: NpvFile
): ScenarioComparison => {
  const baseTotals = totalsOf(base);
  const otherTotals = totalsOf(other);
  return {
    baseId,
    otherId,
    base: baseTotals,
    other: otherTotals,
    delta: {
      preTax: otherTotals.preTax - baseTotals.preTax,
      withTax: otherTotals.withTax - baseTotals.withTax
    }
  };
};

export const submittedOf = (entries: readonly ScenarioEntry[]): ScenarioEntry | null =>
  entries.find((entry) => entry.is_submitted) ?? null;

export const alternativesOf = (
  entries: readonly ScenarioEntry[]
): readonly ScenarioEntry[] => entries.filter((entry) => !entry.is_submitted);
