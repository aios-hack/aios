const EDITABLE = new Set(['INPUT', 'TEXTAREA', 'SELECT']);

export const isEditableTarget = (target: EventTarget | null): boolean => {
  if (target === null || !(target instanceof HTMLElement)) {
    return false;
  }
  return EDITABLE.has(target.tagName) || target.isContentEditable === true;
};

export const isInsideScroller = (target: EventTarget | null): boolean => {
  let node = target instanceof HTMLElement ? target : null;
  while (node !== null) {
    if (node.scrollHeight > node.clientHeight + 1) {
      const overflow = getComputedStyle(node).overflowY;
      if (overflow === 'auto' || overflow === 'scroll') {
        return true;
      }
    }
    node = node.parentElement;
  }
  return false;
};
