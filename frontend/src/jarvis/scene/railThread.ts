export const BEAD_GAP = 12;
export const THREAD_HEIGHT = 12;

export const threadPath = (count: number, pitch: number): string => {
  if (count < 2) {
    return '';
  }
  const middle = THREAD_HEIGHT / 2;
  const parts = [`M 0 ${middle}`];
  for (let index = 1; index < count; index += 1) {
    const from = (index - 1) * pitch;
    const to = index * pitch;
    const centre = (from + to) / 2;
    parts.push(`Q ${centre} ${middle - 4} ${to} ${middle}`);
  }
  return parts.join(' ');
};

export const threadLength = (count: number, pitch: number): number =>
  count < 2 ? 0 : (count - 1) * pitch * 1.04;
