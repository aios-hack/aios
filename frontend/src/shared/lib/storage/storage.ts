const store = (): Storage | null => {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage;
  } catch {
    return null;
  }
};

export const readStored = (key: string): string | null => {
  const target = store();
  if (target === null) {
    return null;
  }
  try {
    return target.getItem(key);
  } catch {
    return null;
  }
};

export const writeStored = (key: string, value: string): void => {
  const target = store();
  if (target === null) {
    return;
  }
  try {
    target.setItem(key, value);
  } catch {
    return;
  }
};

export const removeStored = (key: string): void => {
  const target = store();
  if (target === null) {
    return;
  }
  try {
    target.removeItem(key);
  } catch {
    return;
  }
};
