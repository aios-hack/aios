export interface LayoutBox {
  left: number;
  top: number;
  width: number;
  height: number;
}

export const layoutBoxOf = (node: HTMLElement, root: HTMLElement): LayoutBox => {
  let left = 0;
  let top = 0;
  let current: HTMLElement | null = node;
  while (current !== null && current !== root) {
    left += current.offsetLeft;
    top += current.offsetTop;
    const parent: Element | null = current.offsetParent;
    if (!(parent instanceof HTMLElement)) {
      break;
    }
    if (parent !== root) {
      left -= parent.scrollLeft;
      top -= parent.scrollTop;
    }
    current = parent;
  }
  return { left, top, width: node.offsetWidth, height: node.offsetHeight };
};
