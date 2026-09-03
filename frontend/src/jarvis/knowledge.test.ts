import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { WORKSPACE_VIEWS, type Workspace } from '../state/ConsoleContext';

interface Bilingual {
  ru: string;
  en: string;
}

interface GuideControl {
  label: Bilingual;
  spotlight?: string;
  hotkey?: string;
}

interface GuideScreen {
  workspace: string;
  view: string;
  title: Bilingual;
  what: Bilingual;
  how_to_read: Bilingual;
  controls?: GuideControl[];
  questions?: unknown[];
}

interface GuideElement {
  id: string;
  title: Bilingual;
  what: Bilingual;
  how_to_read: Bilingual;
  controls?: GuideControl[];
}

interface GuideFile {
  screens: GuideScreen[];
  elements?: GuideElement[];
}

const srcDir = join(__dirname, '..');
const guidePath = join(srcDir, '..', 'public', 'jarvis', 'knowledge', 'guide.json');
const guide = JSON.parse(readFileSync(guidePath, 'utf-8')) as GuideFile;

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

const spotlightsOf = (controls: GuideControl[] | undefined): string[] =>
  (controls ?? [])
    .map((control) => control.spotlight)
    .filter((value): value is string => typeof value === 'string' && value.length > 0);

const allSpotlights = [
  ...guide.screens.flatMap((screen) => spotlightsOf(screen.controls)),
  ...(guide.elements ?? []).flatMap((element) => spotlightsOf(element.controls))
];

const bothLanguages = (value: Bilingual | undefined): boolean =>
  typeof value?.ru === 'string' &&
  value.ru.length > 0 &&
  typeof value?.en === 'string' &&
  value.en.length > 0;

describe('guide.json covers every console screen', () => {
  it('has an entry for every workspace/view pair in WORKSPACE_VIEWS', () => {
    const expected: string[] = [];
    for (const [workspace, views] of Object.entries(WORKSPACE_VIEWS)) {
      for (const view of views as readonly string[]) {
        expected.push(`${workspace}/${view}`);
      }
    }
    const covered = guide.screens.map((screen) => `${screen.workspace}/${screen.view}`);
    expect(expected.filter((pair) => !covered.includes(pair)).sort()).toEqual([]);
  });

  it('names a workspace that exists in WORKSPACE_VIEWS for every screen', () => {
    const workspaces = Object.keys(WORKSPACE_VIEWS);
    for (const screen of guide.screens) {
      expect(workspaces, `${screen.workspace}/${screen.view}`).toContain(screen.workspace);
      const views = WORKSPACE_VIEWS[screen.workspace as Workspace] as readonly string[];
      expect(views, `${screen.workspace}/${screen.view}`).toContain(screen.view);
    }
  });

  it('writes title, what and how_to_read in both languages', () => {
    for (const screen of guide.screens) {
      const id = `${screen.workspace}/${screen.view}`;
      expect(bothLanguages(screen.title), `${id} title`).toBe(true);
      expect(bothLanguages(screen.what), `${id} what`).toBe(true);
      expect(bothLanguages(screen.how_to_read), `${id} how_to_read`).toBe(true);
    }
    for (const element of guide.elements ?? []) {
      expect(bothLanguages(element.title), `${element.id} title`).toBe(true);
      expect(bothLanguages(element.what), `${element.id} what`).toBe(true);
      expect(bothLanguages(element.how_to_read), `${element.id} how_to_read`).toBe(true);
    }
  });

  it('labels every control in both languages', () => {
    const controls = [
      ...guide.screens.flatMap((screen) => screen.controls ?? []),
      ...(guide.elements ?? []).flatMap((element) => element.controls ?? [])
    ];
    expect(controls.length).toBeGreaterThan(0);
    for (const control of controls) {
      expect(bothLanguages(control.label)).toBe(true);
    }
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
    const placed = [...sourceText.matchAll(/guide="([a-z0-9-]+)"/g)].map(
      (match) => match[1]
    );
    const known = new Set(allSpotlights);
    expect([...new Set(placed)].filter((anchor) => !known.has(anchor)).sort()).toEqual([]);
  });
});
