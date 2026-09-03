export const GUIDE_ATTRIBUTE = 'data-guide';
export const SPOTLIGHT_CLASS = 'jarvis-spotlight';
export const SPOTLIGHT_MS = 3000;

export const guideSelector = (anchor: string): string =>
  `[${GUIDE_ATTRIBUTE}="${CSS.escape(anchor)}"]`;

export const findGuideAnchor = (anchor: string, root: ParentNode): Element | null => {
  if (anchor.length === 0) {
    return null;
  }
  try {
    return root.querySelector(guideSelector(anchor));
  } catch {
    return null;
  }
};

export const spotlightAnchor = (
  anchor: string,
  root: ParentNode = document,
  durationMs = SPOTLIGHT_MS
): (() => void) | null => {
  const element = findGuideAnchor(anchor, root);
  if (element === null) {
    return null;
  }
  element.classList.add(SPOTLIGHT_CLASS);
  if (typeof element.scrollIntoView === 'function') {
    element.scrollIntoView({ block: 'center', inline: 'nearest' });
  }
  const id = setTimeout(() => element.classList.remove(SPOTLIGHT_CLASS), durationMs);
  return () => {
    clearTimeout(id);
    element.classList.remove(SPOTLIGHT_CLASS);
  };
};
