import { lazy, type ComponentType, type LazyExoticComponent } from 'react';
import { WORKSPACE_VIEWS, type Workspace, type WorkspaceView } from '@/shared/router/routes';

export type PageComponent = LazyExoticComponent<ComponentType>;

const page = (load: () => Promise<{ default: ComponentType }>): PageComponent => lazy(load);

export const PAGES: Record<string, PageComponent> = {
  'overview/fund': page(() =>
    import('@/pages/overview').then((m) => ({ default: m.Overview }))
  ),
  'field/projection': page(() =>
    import('@/pages/field-projection').then((m) => ({ default: m.FieldProjection }))
  ),
  'field/maps': page(() => import('@/pages/field-maps').then((m) => ({ default: m.FieldMaps }))),
  'history/matrix': page(() =>
    import('@/pages/history-matrix').then((m) => ({ default: m.Chronomap }))
  ),
  'history/wall': page(() =>
    import('@/pages/history-wall').then((m) => ({ default: m.WallOfLives }))
  ),
  'history/table': page(() =>
    import('@/pages/history-table').then((m) => ({ default: m.HistoryTable }))
  ),
  'decisions/council': page(() => import('@/pages/council').then((m) => ({ default: m.Council }))),
  'decisions/rules': page(() => import('@/pages/rules').then((m) => ({ default: m.Rules }))),
  'money/rank': page(() => import('@/pages/money-rank').then((m) => ({ default: m.MoneyRank }))),
  'money/comparison': page(() =>
    import('@/pages/money-comparison').then((m) => ({ default: m.MoneyComparison }))
  ),
  'money/constraints': page(() =>
    import('@/pages/money-constraints').then((m) => ({ default: m.MoneyConstraints }))
  )
};

export const pageKey = (workspace: Workspace, view: WorkspaceView): string =>
  `${workspace}/${view}`;

export const pageFor = (workspace: Workspace, view: WorkspaceView): PageComponent | null =>
  PAGES[pageKey(workspace, view)] ?? null;

export const ROUTED_PAGE_KEYS: readonly string[] = Object.entries(WORKSPACE_VIEWS).flatMap(
  ([workspace, views]) => (views as readonly string[]).map((view) => `${workspace}/${view}`)
);
