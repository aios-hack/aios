import { describe, expect, it } from 'vitest';
import type { NpvFile, ScenarioEntry } from '../../api/types';
import {
  alternativesOf,
  compareScenarios,
  submittedOf,
  totalsOf,
  valueFor
} from './comparison';

const npvFile = (preTax: number, withTax: number): NpvFile => ({
  wells: [],
  total: { pre_tax: preTax, with_allocated_tax: withTax },
  npv_methodology: withTax
});

const entry = (id: string, submitted: boolean): ScenarioEntry => ({
  id,
  is_submitted: submitted,
  converged: true,
  self_consistent: true,
  npv_methodology: submitted ? 100 : null,
  config_hash: 'hash',
  constraints: {
    empty: false,
    injection_limits: 0,
    liquid_limits: 0,
    production_floors: 0,
    watercut_limits: 0,
    well_outages: 0,
    infrastructure: 0,
    outage_wells: [],
    years: []
  }
});

describe('сравнение сценариев', () => {
  it('считает разницу как гипотеза минус сданный', () => {
    const result = compareScenarios(
      'base',
      'whatif',
      npvFile(1000, 700),
      npvFile(1250, 780)
    );
    expect(result.delta.preTax).toBe(250);
    expect(result.delta.withTax).toBe(80);
  });

  it('даёт отрицательную разницу, когда гипотеза хуже сданного', () => {
    const result = compareScenarios(
      'base',
      'whatif',
      npvFile(1000, 700),
      npvFile(900, 650)
    );
    expect(result.delta.preTax).toBe(-100);
    expect(result.delta.withTax).toBe(-50);
  });

  it('берёт величину по выбранному налоговому режиму', () => {
    const totals = totalsOf(npvFile(1000, 700));
    expect(valueFor(totals, 'preTax')).toBe(1000);
    expect(valueFor(totals, 'withTax')).toBe(700);
  });

  it('находит сданный сценарий и отделяет гипотезы', () => {
    const entries = [entry('a', false), entry('base', true), entry('b', false)];
    expect(submittedOf(entries)?.id).toBe('base');
    expect(alternativesOf(entries).map((item) => item.id)).toEqual(['a', 'b']);
  });

  it('возвращает null, когда сданного сценария нет', () => {
    expect(submittedOf([entry('a', false)])).toBeNull();
  });
});

describe('знак разницы задаёт акцент на плашке', () => {
  it('считает гипотезу лучше только при строго положительной разнице', () => {
    const better = compareScenarios('base', 'whatif', npvFile(1000, 700), npvFile(1250, 780));
    expect(valueFor(better.delta, 'preTax') > 0).toBe(true);
    expect(valueFor(better.delta, 'withTax') > 0).toBe(true);
  });

  it('не считает равный результат улучшением', () => {
    const same = compareScenarios('base', 'whatif', npvFile(1000, 700), npvFile(1000, 700));
    expect(valueFor(same.delta, 'preTax')).toBe(0);
    expect(valueFor(same.delta, 'preTax') > 0).toBe(false);
  });

  it('меняет знак вместе с налоговым режимом, когда режимы расходятся', () => {
    const mixed = compareScenarios('base', 'whatif', npvFile(1000, 700), npvFile(1100, 650));
    expect(valueFor(mixed.delta, 'preTax') > 0).toBe(true);
    expect(valueFor(mixed.delta, 'withTax') > 0).toBe(false);
  });
});
