const HEAD_LENGTH = 12;

export const ProvenanceHash = ({ value }: { value: string }) => {
  const head = value.slice(0, HEAD_LENGTH);
  if (head.length >= value.length) {
    return <span className="run-provenance-hash">{value}</span>;
  }
  return (
    <abbr className="run-provenance-hash" title={value}>
      {head}…
    </abbr>
  );
};
