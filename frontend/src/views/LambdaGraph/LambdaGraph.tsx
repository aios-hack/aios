import { useMemo, useState } from 'react';
import { useDataset } from '../../data';
import { useT } from '../../i18n/I18nContext';
import { useTimeline } from '../../state/TimelineContext';
import { ViewStatus } from '../../ui/ViewStatus';
import { GroupLegend, MetaPanel, SelectionPanel, ThresholdControl, WindowBadge } from './GraphPanels';
import { GraphPlot } from './GraphPlot';
import {
  buildSelection,
  EDGES_PER_PRODUCER,
  topEdgesPerProducer,
  visibleEdges,
  type WellFluidState
} from './model';
import './LambdaGraph.css';

export const LambdaGraph = () => {
  const t = useT();
  const graph = useDataset('graph');
  const { selectedWell, selectWell, timeline, stepIndex } = useTimeline();
  const [threshold, setThreshold] = useState<number | null>(null);

  const data = graph.status === 'ready' ? graph.data : null;
  const bounds = useMemo(() => {
    if (data === null) {
      return { min: 0, max: 0 };
    }
    const weights = data.edges.map((edge) => Math.abs(edge.weight));
    // Верхняя граница чуть выше сильнейшей связи: при max, равном её весу,
    // фильтр `>=` всегда пропускает это ребро и обнулить граф нельзя.
    const top = weights.length > 0 ? Math.max(...weights) : 0;
    return {
      min: weights.length > 0 ? Math.min(...weights) : 0,
      max: top > 0 ? top * 1.02 : 0
    };
  }, [data]);

  const active = threshold ?? bounds.min;
  const selection = useMemo(
    () =>
      data !== null && selectedWell !== null
        ? buildSelection(selectedWell, data, active)
        : null,
    [data, selectedWell, active]
  );

  const wellStates = useMemo(() => {
    const map = new Map<string, WellFluidState>();
    if (timeline.status !== 'ready') {
      return map;
    }
    const step = timeline.data.steps[stepIndex];
    if (step === undefined) {
      return map;
    }
    for (const well of step.wells) {
      map.set(well.well, {
        watercut: well.availability === 'NOT_COMMISSIONED' ? null : well.watercut,
        commissioned: well.availability !== 'NOT_COMMISSIONED'
      });
    }
    return map;
  }, [timeline, stepIndex]);

  if (graph.status === 'loading') {
    return <ViewStatus kind="loading" title={t('graph.loading')} />;
  }
  if (graph.status === 'error' || data === null) {
    return <ViewStatus kind="error" title={t('graph.error')} hint={t('graph.errorHint')} />;
  }

  // На минимальном пороге ограничение снимается: иначе полный набор связей
  // недостижим — счётчик замирает на «177 из 181».
  const capEdges = active > bounds.min;
  const shown = topEdgesPerProducer(
    visibleEdges(data.edges, active),
    capEdges ? EDGES_PER_PRODUCER : null
  ).length;

  return (
    <section className="lambda-graph">
      <ThresholdControl
        value={active}
        min={bounds.min}
        max={bounds.max}
        shown={shown}
        total={data.edges.length}
        onChange={setThreshold}
      />
      <div className="lambda-graph-stage">
        <div className="lambda-graph-canvas">
          {data.edges.length === 0 ? (
            <ViewStatus kind="empty" title={t('graph.empty')} hint={t('graph.emptyHint')} />
          ) : (
            <GraphPlot
              data={data}
              threshold={active}
              capEdges={capEdges}
              selection={selection}
              wellStates={wellStates}
              onSelect={selectWell}
            />
          )}
        </div>
        <div className="lambda-graph-panels">
          {selection !== null && (
            <SelectionPanel selection={selection} onClear={() => selectWell(null)} />
          )}
          <GroupLegend data={data} />
          <MetaPanel meta={data.meta} />
          <WindowBadge window={data.window} />
          <p className="lambda-graph-hint">{t('graph.hint')}</p>
        </div>
      </div>
    </section>
  );
};
