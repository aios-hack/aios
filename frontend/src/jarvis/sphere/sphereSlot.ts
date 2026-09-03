export interface SlotRect {
  left: number;
  top: number;
  width: number;
  height: number;
}

export const centerOf = (rect: SlotRect): { x: number; y: number } => ({
  x: rect.left + rect.width / 2,
  y: rect.top + rect.height / 2
});

export const readSlot = (element: Element | null): SlotRect | null => {
  if (element === null || typeof element.getBoundingClientRect !== 'function') {
    return null;
  }
  const rect = element.getBoundingClientRect();
  if (rect.width <= 0 || rect.height <= 0) {
    return null;
  }
  return { left: rect.left, top: rect.top, width: rect.width, height: rect.height };
};
