import enCommon from './en/common.json';
import enGraph from './en/graph.json';
import enMap from './en/map.json';
import enNpv from './en/npv.json';
import enSteps from './en/steps.json';
import enWellcard from './en/wellcard.json';
import ruCommon from './ru/common.json';
import ruGraph from './ru/graph.json';
import ruMap from './ru/map.json';
import ruNpv from './ru/npv.json';
import ruSteps from './ru/steps.json';
import ruWellcard from './ru/wellcard.json';

export type Lang = 'ru' | 'en';

const withNamespace = (
  namespace: string,
  entries: Record<string, string>
): Record<string, string> =>
  Object.fromEntries(
    Object.entries(entries).map(([key, value]) => [`${namespace}.${key}`, value])
  );

const buildDictionary = (
  common: Record<string, string>,
  namespaces: Record<string, Record<string, string>>
): Record<string, string> =>
  Object.entries(namespaces).reduce(
    (dictionary, [namespace, entries]) => ({
      ...dictionary,
      ...withNamespace(namespace, entries)
    }),
    { ...common }
  );

export const dictionaries: Record<Lang, Record<string, string>> = {
  ru: buildDictionary(ruCommon, {
    graph: ruGraph,
    map: ruMap,
    steps: ruSteps,
    wellcard: ruWellcard,
    npv: ruNpv
  }),
  en: buildDictionary(enCommon, {
    graph: enGraph,
    map: enMap,
    steps: enSteps,
    wellcard: enWellcard,
    npv: enNpv
  })
};
