export interface TraceRecord {
  rule: string;
  inputs: Record<string, number>;
  decision: string;
}

export type TraceFile = Record<string, Record<string, TraceRecord[]>>;
