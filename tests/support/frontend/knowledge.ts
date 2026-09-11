import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { publicPath } from './paths';

export const KNOWLEDGE_LANGS = ['ru', 'en'] as const;

export type KnowledgeLang = (typeof KNOWLEDGE_LANGS)[number];
export type KnowledgeName = 'glossary' | 'guide' | 'system';

export const knowledgeRoot = (): string => publicPath('jarvis', 'knowledge');

export const knowledgePath = (name: KnowledgeName): string =>
  join(knowledgeRoot(), `${name}.json`);

export const knowledgeTextPath = (lang: KnowledgeLang, name: KnowledgeName): string =>
  join(knowledgeRoot(), 'i18n', lang, `${name}.json`);

export const knowledgeFile = <T>(name: KnowledgeName): T =>
  JSON.parse(readFileSync(knowledgePath(name), 'utf-8')) as T;

export const knowledgeText = <T>(lang: KnowledgeLang, name: KnowledgeName): T =>
  JSON.parse(readFileSync(knowledgeTextPath(lang, name), 'utf-8')) as T;

export interface GuideControl {
  spotlight?: string;
  hotkey?: string;
}

export interface GuideScreen {
  workspace: string;
  view: string;
  controls?: GuideControl[];
}

export interface GuideElement {
  id: string;
  controls?: GuideControl[];
}

export interface GuideFile {
  version: number;
  screens: GuideScreen[];
  elements?: GuideElement[];
}

export interface GuideEntryText {
  title: string;
  what: string;
  how_to_read: string;
  controls: string[];
  questions: string[];
}

export interface GuideTexts {
  notice: string;
  screens: Record<string, GuideEntryText>;
  elements: Record<string, GuideEntryText>;
}

export interface TermPlace {
  workspace: string;
  view: string;
  spotlight?: string;
}

export interface Term {
  id: string;
  aliases: string[];
  formula?: string;
  unit?: string;
  source: string;
  where_in_platform: TermPlace[];
  related: string[];
}

export interface GlossaryFile {
  version: number;
  terms: Term[];
}

export interface TermText {
  term: string;
  definition: string;
  where_in_platform: string[];
}

export interface GlossaryTexts {
  notice: string;
  terms: Record<string, TermText>;
}

export interface SystemNode {
  id: string;
  kind: string;
  doc?: string;
  route?: { workspace: string; view: string };
  files: string[];
}

export interface SystemEdge {
  from: string;
  to: string;
}

export interface SystemFile {
  version: number;
  nodes: SystemNode[];
  edges: SystemEdge[];
}

export interface SystemTexts {
  source: string;
  nodes: Record<string, { label: string; summary: string }>;
  edges: Record<string, { label: string }>;
}

export const edgeKey = (edge: SystemEdge): string => `${edge.from}->${edge.to}`;
