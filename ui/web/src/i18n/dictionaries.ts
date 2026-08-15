import enCommon from './en/common.json';
import enMap from './en/map.json';
import enSteps from './en/steps.json';
import ruCommon from './ru/common.json';
import ruMap from './ru/map.json';
import ruSteps from './ru/steps.json';

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
  map: Record<string, string>,
  steps: Record<string, string>
): Record<string, string> => ({
  ...common,
  ...withNamespace('map', map),
  ...withNamespace('steps', steps)
});

export const dictionaries: Record<Lang, Record<string, string>> = {
  ru: buildDictionary(ruCommon, ruMap, ruSteps),
  en: buildDictionary(enCommon, enMap, enSteps)
};
