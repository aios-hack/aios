export type ProvenanceKind = 'measured' | 'synthetic' | 'general' | 'knowledge' | 'unknown';

export const provenanceKindOf = (provenance: string): ProvenanceKind => {
  const value = provenance.trim().toLowerCase();
  if (value.length === 0 || value === 'none') {
    return 'unknown';
  }
  if (value === 'general') {
    return 'general';
  }
  if (value === 'knowledge') {
    return 'knowledge';
  }
  if (value.includes('synthetic') || value.includes('demo')) {
    return 'synthetic';
  }
  return 'measured';
};

export const provenanceTitleKey = (kind: ProvenanceKind): string => {
  if (kind === 'general') {
    return 'jarvis.provenanceGeneral';
  }
  if (kind === 'knowledge') {
    return 'jarvis.provenanceKnowledge';
  }
  return `trust.provenance.${kind}`;
};
