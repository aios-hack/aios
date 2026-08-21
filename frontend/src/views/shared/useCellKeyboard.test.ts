import { describe, expect, it, vi } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { useCellKeyboard } from './useCellKeyboard';

const keyEvent = (key: string) =>
  ({ key, preventDefault: vi.fn(), stopPropagation: vi.fn() }) as never;

describe('cell keyboard navigation', () => {
  it('moves the cursor with the arrows inside the data bounds', () => {
    const { result } = renderHook(() =>
      useCellKeyboard({ rowCount: 3, columnCount: 4, onCommit: vi.fn() })
    );
    act(() => result.current.onKeyDown(keyEvent('ArrowRight')));
    act(() => result.current.onKeyDown(keyEvent('ArrowDown')));
    expect(result.current.cursor).toEqual({ row: 1, column: 1 });
  });

  it('never leaves the matrix at its edges', () => {
    const { result } = renderHook(() =>
      useCellKeyboard({ rowCount: 2, columnCount: 2, onCommit: vi.fn() })
    );
    act(() => result.current.onKeyDown(keyEvent('ArrowUp')));
    act(() => result.current.onKeyDown(keyEvent('ArrowLeft')));
    expect(result.current.cursor).toEqual({ row: 0, column: 0 });
  });

  it('commits the cursor on Enter', () => {
    const onCommit = vi.fn();
    const { result } = renderHook(() =>
      useCellKeyboard({ rowCount: 3, columnCount: 3, onCommit })
    );
    act(() => result.current.onKeyDown(keyEvent('ArrowDown')));
    act(() => result.current.onKeyDown(keyEvent('Enter')));
    expect(onCommit).toHaveBeenCalledWith({ row: 1, column: 0 });
  });

  it('does nothing when the data is empty', () => {
    const onCommit = vi.fn();
    const { result } = renderHook(() =>
      useCellKeyboard({ rowCount: 0, columnCount: 0, onCommit })
    );
    act(() => result.current.onKeyDown(keyEvent('Enter')));
    expect(onCommit).not.toHaveBeenCalled();
  });
});
