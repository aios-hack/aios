import enChrono from './en/chrono.json';
import enCouncil from './en/council.json';
import enDemo from './en/demo.json';
import enCommon from './en/common.json';
import enHistory from './en/history.json';
import enInspector from './en/inspector.json';
import enNpv from './en/npv.json';
import enPalette from './en/palette.json';
import enProjection from './en/projection.json';
import enScenarios from './en/scenarios.json';
import enSteps from './en/steps.json';
import enTrust from './en/trust.json';
import enWall from './en/wall.json';
import enWellcard from './en/wellcard.json';
import ruChrono from './ru/chrono.json';
import ruCouncil from './ru/council.json';
import ruDemo from './ru/demo.json';
import ruCommon from './ru/common.json';
import ruHistory from './ru/history.json';
import ruInspector from './ru/inspector.json';
import ruNpv from './ru/npv.json';
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
    steps: ruSteps,
    wellcard: ruWellcard,
    npv: ruNpv,
    scenarios: ruScenarios,
    chrono: ruChrono,
    council: ruCouncil,
    demo: ruDemo,
    projection: ruProjection,
    palette: ruPalette,
    trust: ruTrust,
    wall: ruWall,
    inspector: ruInspector
  }),
  en: buildDictionary(enCommon, {
    history: enHistory,
    steps: enSteps,
    wellcard: enWellcard,
    npv: enNpv,
    scenarios: enScenarios,
    chrono: enChrono,
    council: enCouncil,
    demo: enDemo,
    projection: enProjection,
    palette: enPalette,
    trust: enTrust,
    wall: enWall,
    inspector: enInspector
  })
};
