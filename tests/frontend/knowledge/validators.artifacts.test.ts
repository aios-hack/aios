import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative, sep } from 'node:path';
import { describe, expect, it } from 'vitest';
import { isAblationFile } from '@/entities/ablation/validate';
import { isGraphFile } from '@/entities/graph/validate';
import { isHierarchyIndexFile, isHierarchyStepFile } from '@/entities/hierarchy/validate';
import { isMapLayerFile, isMapsIndexFile } from '@/entities/maps/validate';
import { isNpvFile } from '@/entities/npv/validate';
import { isScenariosFile } from '@/entities/scenarios/validate';
import { isTimelineFile } from '@/entities/timeline/validate';
import { isTraceFile } from '@/entities/trace/validate';
import { isWellsFile } from '@/entities/wells/validate';
import { publicPath } from '@support/paths';

describe('shipped artifacts', () => {
  const read = (name: string): unknown =>
    JSON.parse(readFileSync(publicPath('data', name), 'utf-8'));

  const cases: [string, (data: unknown) => boolean][] = [
    ['timeline.json', isTimelineFile],
    ['wells.json', isWellsFile],
    ['npv.json', isNpvFile],
    ['graph.json', isGraphFile],
    ['scenarios.json', isScenariosFile],
    ['ablation.json', isAblationFile],
    ['trace.json', isTraceFile],
    ['whatif-injection-cut/trace.json', isTraceFile],
    ['whatif-injection-cut/timeline.json', isTimelineFile],
    ['whatif-injection-cut/graph.json', isGraphFile],
    ['base/timeline.json', isTimelineFile],
    ['base/graph.json', isGraphFile],
    ['policy-plan/timeline.json', isTimelineFile],
    ['policy-plan/npv.json', isNpvFile],
    ['base/npv.json', isNpvFile],
    ['base/ablation.json', isAblationFile],
    ['base/trace.json', isTraceFile],
    ['policy-plan/graph.json', isGraphFile],
    ['policy-plan/ablation.json', isAblationFile],
    ['policy-plan/trace.json', isTraceFile],
    ['whatif-injection-cut/npv.json', isNpvFile],
    ['whatif-injection-cut/ablation.json', isAblationFile],
    ['maps/index.json', isMapsIndexFile],
    ['maps/PORO/12.json', isMapLayerFile],
    ['maps/PERMX/12.json', isMapLayerFile],
    ['maps/FIP_ZONE/12.json', isMapLayerFile],
    ['hierarchy-index.json', isHierarchyIndexFile],
    ['base/hierarchy-index.json', isHierarchyIndexFile],
    ['policy-plan/hierarchy-index.json', isHierarchyIndexFile],
    ['whatif-injection-cut/hierarchy-index.json', isHierarchyIndexFile],
    ['hierarchy/0.json', isHierarchyStepFile],
    ['base/hierarchy/0.json', isHierarchyStepFile]
  ];

  it.each(cases)('accepts the shipped %s', (name, validate) => {
    expect(validate(read(name))).toBe(true);
  });

  const root = publicPath('data');

  const walk = (dir: string): string[] =>
    readdirSync(dir).flatMap((entry) => {
      if (entry.startsWith('.')) {
        return [];
      }
      const full = join(dir, entry);
      if (statSync(full).isDirectory()) {
        return walk(full);
      }
      return entry.endsWith('.json') ? [relative(root, full).split(sep).join('/')] : [];
    });

  const VALIDATED = new Set(cases.map(([name]) => name));

  const UNVALIDATED = new Set([
    'bundles/base.json',
    'bundles/policy-plan.json',
    'bundles/whatif-injection-cut.json',
    'demo-script.json'
  ]);

  const MAP_LAYER = /^maps\/[A-Z_]+\/\d+\.json$/;

  const HIERARCHY_STEP = /^(?:[a-z-]+\/)?hierarchy\/\d+\.json$/;

  it('runs every shipped artifact through a validator', () => {
    const missing = walk(root).filter(
      (name) =>
        !VALIDATED.has(name) &&
        !UNVALIDATED.has(name) &&
        !MAP_LAYER.test(name) &&
        !HIERARCHY_STEP.test(name)
    );
    expect(missing).toEqual([]);
  });

  it('keeps the validated list pointing at files that exist', () => {
    const present = new Set(walk(root));
    expect([...VALIDATED].filter((name) => !present.has(name))).toEqual([]);
  });

  const SYNTHETIC_PROVENANCE = 'synthetic-demo';

  const metaBlocks = (data: unknown): Record<string, unknown>[] => {
    if (typeof data !== 'object' || data === null || Array.isArray(data)) {
      return [];
    }
    const record = data as Record<string, unknown>;
    const found: unknown[] = [record.meta, record.__meta__];
    for (const value of Object.values(record)) {
      if (typeof value === 'object' && value !== null && !Array.isArray(value)) {
        const nested = value as Record<string, unknown>;
        found.push(nested.meta, nested.__meta__, nested);
      }
    }
    return found.filter(
      (item): item is Record<string, unknown> =>
        typeof item === 'object' && item !== null && !Array.isArray(item)
    );
  };

  const isSynthetic = (data: unknown): boolean =>
    metaBlocks(data).some(
      (meta) => meta.synthetic === true || meta.provenance === SYNTHETIC_PROVENANCE
    );

  const syntheticArtifacts = (): string[] =>
    walk(root).filter((name) => {
      try {
        return isSynthetic(read(name));
      } catch {
        return false;
      }
    });

  it.fails('ships no synthetic artifact in the shop window', () => {
    expect(syntheticArtifacts()).toEqual([]);
  });

  it('keeps the synthetic debt visible instead of letting it grow quietly', () => {
    const known = [
      'bundles/whatif-injection-cut.json',
      'demo-script.json',
      'whatif-injection-cut/ablation.json',
      'whatif-injection-cut/graph.json',
      'whatif-injection-cut/hierarchy-index.json',
      'whatif-injection-cut/npv.json',
      'whatif-injection-cut/timeline.json',
      'whatif-injection-cut/trace.json'
    ];
    expect(syntheticArtifacts().sort()).toEqual(known);
  });

  it('ships no invented money in any ablation artifact', () => {
    const ablations = walk(root).filter((name) => name.endsWith('ablation.json'));
    expect(ablations.length).toBeGreaterThan(0);
    for (const name of ablations) {
      const file = read(name) as { rules: { delta_npv: unknown; share: unknown }[] };
      for (const rule of file.rules) {
        expect(rule.delta_npv, name).toBeNull();
        expect(rule.share, name).toBeNull();
      }
    }
  });

  it('keeps the screens the curator opens off synthetic data', () => {
    const clean = ['timeline.json', 'npv.json', 'graph.json', 'trace.json'];
    expect(clean.filter((name) => isSynthetic(read(name)))).toEqual([]);
  });
});
