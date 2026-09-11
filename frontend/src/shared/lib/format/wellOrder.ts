const SPLIT = /^(\D*)(\d+)(.*)$/;

const isBlank = (well: string): boolean => well.trim().length === 0;

export const compareWellIds = (a: string, b: string): number => {
  if (isBlank(a) || isBlank(b)) {
    if (isBlank(a) && isBlank(b)) {
      return a.localeCompare(b);
    }
    return isBlank(a) ? 1 : -1;
  }
  const partsA = SPLIT.exec(a);
  const partsB = SPLIT.exec(b);
  if (partsA === null || partsB === null) {
    return a.localeCompare(b);
  }
  const prefix = partsA[1].localeCompare(partsB[1]);
  if (prefix !== 0) {
    return prefix;
  }
  const numeric = Number(partsA[2]) - Number(partsB[2]);
  if (numeric !== 0) {
    return numeric;
  }
  return partsA[3].localeCompare(partsB[3]) || a.localeCompare(b);
};
