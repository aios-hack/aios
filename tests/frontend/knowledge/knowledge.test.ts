import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { WORKSPACE_VIEWS, type Workspace } from '@/shared/router/routes';
import { srcPath } from '@support/paths';
import {
  knowledgeFile,
  knowledgeText,
  KNOWLEDGE_LANGS,
  type GuideFile,
  type GuideTexts
} from '@support/knowledge';

const srcDir = srcPath();
const guide = knowledgeFile<GuideFile>('guide');
const guideTexts: Record<string, GuideTexts> = Object.fromEntries(
  KNOWLEDGE_LANGS.map((lang) => [lang, knowledgeText<GuideTexts>(lang, 'guide')])
);

const collectSources = (dir: string, found: string[] = []): string[] => {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      collectSources(full, found);
      continue;
    }
    if (/\.tsx?$/.test(entry) && !entry.includes('.test.')) {
      found.push(full);
    }
  }
  return found;
};

const sourceText = collectSources(srcDir)
  .map((file) => readFileSync(file, 'utf-8'))
  .join('\n');

const screenKey = (screen: { workspace: string; view: string }): string =>
  `${screen.workspace}/${screen.view}`;

const spotlightsOf = (controls: { spotlight?: string }[] | undefined): string[] =>
  (controls ?? [])
    .map((control) => control.spotlight)
    .filter((value): value is string => typeof value === 'string' && value.length > 0);

const allSpotlights = [
  ...guide.screens.flatMap((screen) => spotlightsOf(screen.controls)),
  ...(guide.elements ?? []).flatMap((element) => spotlightsOf(element.controls))
];

const filled = (value: unknown): boolean => typeof value === 'string' && value.length > 0;

describe('guide.json covers every console screen', () => {
  it('has an entry for every workspace/view pair in WORKSPACE_VIEWS', () => {
    const expected: string[] = [];
    for (const [workspace, views] of Object.entries(WORKSPACE_VIEWS)) {
      for (const view of views as readonly string[]) {
        expected.push(`${workspace}/${view}`);
      }
    }
    const covered = guide.screens.map(screenKey);
    expect(expected.filter((pair) => !covered.includes(pair)).sort()).toEqual([]);
  });

  it('names a workspace that exists in WORKSPACE_VIEWS for every screen', () => {
    const workspaces = Object.keys(WORKSPACE_VIEWS);
    for (const screen of guide.screens) {
      expect(workspaces, screenKey(screen)).toContain(screen.workspace);
      const views = WORKSPACE_VIEWS[screen.workspace as Workspace] as readonly string[];
      expect(views, screenKey(screen)).toContain(screen.view);
    }
  });

  it('keeps every language string out of the neutral file', () => {
    const raw = JSON.stringify(guide);
    expect(raw).not.toContain('"ru"');
    expect(raw).not.toContain('"en"');
  });

  it('writes title, what and how_to_read in every language', () => {
    for (const lang of KNOWLEDGE_LANGS) {
      const texts = guideTexts[lang] as GuideTexts;
      for (const screen of guide.screens) {
        const entry = texts.screens[screenKey(screen)];
        expect(entry, `${lang} ${screenKey(screen)}`).toBeDefined();
        for (const field of ['title', 'what', 'how_to_read'] as const) {
          expect(filled(entry?.[field]), `${lang} ${screenKey(screen)} ${field}`).toBe(true);
        }
      }
      for (const element of guide.elements ?? []) {
        const entry = texts.elements[element.id];
        expect(entry, `${lang} ${element.id}`).toBeDefined();
        for (const field of ['title', 'what', 'how_to_read'] as const) {
          expect(filled(entry?.[field]), `${lang} ${element.id} ${field}`).toBe(true);
        }
      }
    }
  });

  it('labels every control in every language, one label per neutral control', () => {
    let counted = 0;
    for (const lang of KNOWLEDGE_LANGS) {
      const texts = guideTexts[lang] as GuideTexts;
      for (const screen of guide.screens) {
        const labels = texts.screens[screenKey(screen)]?.controls ?? [];
        expect(labels.length, `${lang} ${screenKey(screen)}`).toBe(
          (screen.controls ?? []).length
        );
        for (const label of labels) {
          expect(filled(label), `${lang} ${screenKey(screen)}`).toBe(true);
          counted += 1;
        }
      }
      for (const element of guide.elements ?? []) {
        const labels = texts.elements[element.id]?.controls ?? [];
        expect(labels.length, `${lang} ${element.id}`).toBe((element.controls ?? []).length);
        for (const label of labels) {
          expect(filled(label), `${lang} ${element.id}`).toBe(true);
          counted += 1;
        }
      }
    }
    expect(counted).toBeGreaterThan(0);
  });
});

describe('every spotlight anchor exists in the markup', () => {
  it('finds a data-guide attribute for each spotlight in guide.json', () => {
    expect(allSpotlights.length).toBeGreaterThan(0);
    const missing = [...new Set(allSpotlights)].filter(
      (anchor) => !sourceText.includes(`"${anchor}"`) && !sourceText.includes(`'${anchor}'`)
    );
    expect(missing.sort()).toEqual([]);
  });

  it('declares no data-guide anchor that guide.json never points at', () => {
    const placed = [...sourceText.matchAll(/guide="([a-z0-9-]+)"/g)].map((match) => match[1]);
    const known = new Set(allSpotlights);
    expect([...new Set(placed)].filter((anchor) => !known.has(anchor)).sort()).toEqual([]);
  });
});
