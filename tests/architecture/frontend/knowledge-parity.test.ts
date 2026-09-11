import { describe, expect, it } from 'vitest';
import {
  edgeKey,
  knowledgeFile,
  knowledgeText,
  KNOWLEDGE_LANGS,
  type GlossaryFile,
  type GlossaryTexts,
  type GuideFile,
  type GuideTexts,
  type SystemFile,
  type SystemTexts
} from '@support/knowledge';

const NAMES = ['glossary', 'guide', 'system'] as const;

const hasLanguageObject = (value: unknown): boolean => {
  if (Array.isArray(value)) {
    return value.some(hasLanguageObject);
  }
  if (typeof value !== 'object' || value === null) {
    return false;
  }
  const keys = Object.keys(value as Record<string, unknown>);
  if (keys.length > 0 && keys.every((key) => (KNOWLEDGE_LANGS as readonly string[]).includes(key))) {
    return true;
  }
  return Object.values(value as Record<string, unknown>).some(hasLanguageObject);
};

describe('the neutral knowledge files carry no language text', () => {
  for (const name of NAMES) {
    it(`${name}.json holds no {ru, en} object`, () => {
      expect(hasLanguageObject(knowledgeFile(name))).toBe(false);
    });
  }
});

describe('every neutral id is translated in every language', () => {
  const glossary = knowledgeFile<GlossaryFile>('glossary');
  const guide = knowledgeFile<GuideFile>('guide');
  const system = knowledgeFile<SystemFile>('system');

  for (const lang of KNOWLEDGE_LANGS) {
    it(`${lang}: every glossary term has text and matching place count`, () => {
      const texts = knowledgeText<GlossaryTexts>(lang, 'glossary');
      expect(texts.notice.length).toBeGreaterThan(0);
      for (const term of glossary.terms) {
        const entry = texts.terms[term.id];
        expect(entry, `${lang} ${term.id}`).toBeDefined();
        expect(entry?.term.length, `${lang} ${term.id} term`).toBeGreaterThan(0);
        expect(entry?.definition.length, `${lang} ${term.id} definition`).toBeGreaterThan(0);
        expect(entry?.where_in_platform.length, `${lang} ${term.id} places`).toBe(
          term.where_in_platform.length
        );
      }
      const known = new Set(glossary.terms.map((term) => term.id));
      expect(Object.keys(texts.terms).filter((id) => !known.has(id))).toEqual([]);
    });

    it(`${lang}: every guide screen and element has text and matching control count`, () => {
      const texts = knowledgeText<GuideTexts>(lang, 'guide');
      for (const screen of guide.screens) {
        const key = `${screen.workspace}/${screen.view}`;
        const entry = texts.screens[key];
        expect(entry, `${lang} ${key}`).toBeDefined();
        expect(entry?.controls.length, `${lang} ${key} controls`).toBe(
          (screen.controls ?? []).length
        );
      }
      for (const element of guide.elements ?? []) {
        const entry = texts.elements[element.id];
        expect(entry, `${lang} ${element.id}`).toBeDefined();
        expect(entry?.controls.length, `${lang} ${element.id} controls`).toBe(
          (element.controls ?? []).length
        );
      }
    });

    it(`${lang}: every system node and edge has a label`, () => {
      const texts = knowledgeText<SystemTexts>(lang, 'system');
      for (const node of system.nodes) {
        const entry = texts.nodes[node.id];
        expect(entry, `${lang} ${node.id}`).toBeDefined();
        expect(entry?.label.length, `${lang} ${node.id} label`).toBeGreaterThan(0);
        expect(entry?.summary.length, `${lang} ${node.id} summary`).toBeGreaterThan(0);
      }
      for (const edge of system.edges) {
        const entry = texts.edges[edgeKey(edge)];
        expect(entry, `${lang} ${edgeKey(edge)}`).toBeDefined();
      }
    });
  }
});
