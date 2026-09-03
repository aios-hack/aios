import enChrono from './en/chrono.json';
import enCouncil from './en/council.json';
import enCommon from './en/common.json';
import enHistory from './en/history.json';
import enInspector from './en/inspector.json';
import enJarvis from './en/jarvis.json';
import enNpv from './en/npv.json';
import enOverview from './en/overview.json';
import enPalette from './en/palette.json';
import enProjection from './en/projection.json';
import enScenarios from './en/scenarios.json';
import enSteps from './en/steps.json';
import enTrust from './en/trust.json';
import enWall from './en/wall.json';
import enWellcard from './en/wellcard.json';
import ruChrono from './ru/chrono.json';
import ruCouncil from './ru/council.json';
import ruCommon from './ru/common.json';
import ruHistory from './ru/history.json';
import ruInspector from './ru/inspector.json';
import ruJarvis from './ru/jarvis.json';
import ruNpv from './ru/npv.json';
import ruOverview from './ru/overview.json';
import ruPalette from './ru/palette.json';
import ruProjection from './ru/projection.json';
import ruScenarios from './ru/scenarios.json';
import ruSteps from './ru/steps.json';
import ruTrust from './ru/trust.json';
import ruWall from './ru/wall.json';
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
    history: ruHistory,
    overview: ruOverview,
    steps: ruSteps,
    wellcard: ruWellcard,
    npv: ruNpv,
    scenarios: ruScenarios,
    chrono: ruChrono,
    council: ruCouncil,
    projection: ruProjection,
    palette: ruPalette,
    trust: ruTrust,
    wall: ruWall,
    inspector: ruInspector,
    jarvis: ruJarvis
  }),
  en: buildDictionary(enCommon, {
    history: enHistory,
    overview: enOverview,
    steps: enSteps,
    wellcard: enWellcard,
    npv: enNpv,
    scenarios: enScenarios,
    chrono: enChrono,
    council: enCouncil,
    projection: enProjection,
    palette: enPalette,
    trust: enTrust,
    wall: enWall,
    inspector: enInspector,
    jarvis: enJarvis
  })
};
