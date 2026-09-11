export type ResourceState<T> =
  | { status: 'loading' }
  | { status: 'error' }
  | { status: 'ready'; data: T };

export const isReady = <T,>(
  state: ResourceState<T>
): state is { status: 'ready'; data: T } => state.status === 'ready';

export const dataOf = <T,>(state: ResourceState<T>): T | null =>
  state.status === 'ready' ? state.data : null;
