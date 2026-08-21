import { useCallback, useState, type KeyboardEvent } from 'react';

export interface CellCursor {
  row: number;
  column: number;
}

interface CellKeyboardOptions {
  rowCount: number;
  columnCount: number;
  onCommit: (cursor: CellCursor) => void;
  onMove?: (cursor: CellCursor) => void;
}

const clamp = (value: number, limit: number): number =>
  limit === 0 ? 0 : Math.min(Math.max(value, 0), limit - 1);

const DELTAS: Record<string, CellCursor> = {
  ArrowUp: { row: -1, column: 0 },
  ArrowDown: { row: 1, column: 0 },
  ArrowLeft: { row: 0, column: -1 },
  ArrowRight: { row: 0, column: 1 }
};

export const useCellKeyboard = ({
  rowCount,
  columnCount,
  onCommit,
  onMove
}: CellKeyboardOptions) => {
  const [cursor, setCursor] = useState<CellCursor>({ row: 0, column: 0 });

  const onKeyDown = useCallback(
    (event: KeyboardEvent<HTMLElement>) => {
      if (rowCount === 0 || columnCount === 0) {
        return;
      }
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        onCommit(cursor);
        return;
      }
      const delta = DELTAS[event.key];
      if (delta === undefined) {
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      const next = {
        row: clamp(cursor.row + delta.row, rowCount),
        column: clamp(cursor.column + delta.column, columnCount)
      };
      setCursor(next);
      onMove?.(next);
    },
    [cursor, rowCount, columnCount, onCommit, onMove]
  );

  return { cursor, setCursor, onKeyDown };
};
