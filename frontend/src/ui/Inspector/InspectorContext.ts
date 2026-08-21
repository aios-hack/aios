export interface WellInspectorContext {
  kind: 'well';
  well: string;
}

export interface ScenarioInspectorContext {
  kind: 'scenario';
  scenarioId: string;
}

export type InspectorContext = WellInspectorContext | ScenarioInspectorContext;
