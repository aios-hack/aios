import type { ReactNode } from 'react';
import { RouterProvider } from '@/shared/router/RouterProvider';
import { PlaybackProvider } from '@/entities/timeline/model/PlaybackContext';
import { HistoryViewProvider } from '@/entities/timeline/model/HistoryViewContext';
import { ProvenanceProvider } from '@/features/provenance-banner/model/ProvenanceContext';
import { ScenarioProvider } from '@/entities/scenarios/model/ScenarioContext';
import { TimelineProvider } from '@/entities/timeline/model/TimelineContext';
import { I18nProvider } from '@/shared/i18n/I18nContext';
import { MorphProvider } from '@/shared/lib/morph';
import { ThemeProvider } from '@/shared/theme/ThemeContext';

const LAYERS = [
  ThemeProvider,
  I18nProvider,
  ScenarioProvider,
  ProvenanceProvider,
  TimelineProvider,
  PlaybackProvider,
  HistoryViewProvider,
  MorphProvider,
  RouterProvider
] as const;

export const AppProviders = ({ children }: { children: ReactNode }) =>
  LAYERS.reduceRight<ReactNode>(
    (tree, Provider) => <Provider>{tree}</Provider>,
    children
  );
