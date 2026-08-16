import { useEffect, useMemo, useState } from 'react';
import type { GraphFile } from '../../api/types';
import { useT } from '../../i18n/I18nContext';
import { useTimeline, type ResourceState } from '../../state/TimelineContext';
import { GroupLegend, MetaPanel, SelectionPanel, ThresholdControl, WindowBadge } from './GraphPanels';
import { GraphPlot } from './GraphPlot';
import { buildSelection, isGraphFile, visibleEdges } from './model';
import './LambdaGraph.css';

const useGraphFile = (): ResourceState<GraphFile> => {
  const [state, setState] = useState<ResourceState<GraphFile>>({ status: 'loading' });

  useEffect(() => {
    let cancelled = false;
    fetch('/data/graph.json')
      .then((response) => {
        if (!response.ok) {
          throw new Error(String(response.status));
        }
        return response.json();
      })
      .then((data: unknown) => {
        if (!cancelled) {
          setState(isGraphFile(data) ? { status: 'ready', data } : { status: 'error' });
        }
      })
      .catch(() => {
        if (!cancelled) {
          setState({ status: 'error' });
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return state;
};

export const LambdaGraph = () => {
  const t = useT();
  const graph = useGraphFile();
  const { selectedWell, selectWell } = useTimeline();
  const [threshold, setThreshold] = useState<number | null>(null);

  const data = graph.status === 'ready' ? graph.data : null;
  const bounds = useMemo(() => {
    if (data === null) {
      return { min: 0, max: 0 };
    }
    const weights = data.edges.map((edge) => Math.abs(edge.weight));
    return {
      min: weights.length > 0 ? Math.min(...weights) : 0,
      max: weights.length > 0 ? Math.max(...weights) : 0
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

  if (graph.status === 'loading') {
    return <p className="lambda-graph-status">{t('graph.loading')}</p>;
  }
  if (graph.status === 'error' || data === null) {
    return (
      <p className="lambda-graph-status lambda-graph-status-error">{t('graph.error')}</p>
    );
  }

  const shown = visibleEdges(data.edges, active).length;

  return (
    <section className="lambda-graph">
      <WindowBadge window={data.window} />
      <p className="lambda-graph-thesis">{t('graph.thesis')}</p>
      <ThresholdControl
        value={active}
        min={bounds.min}
        max={bounds.max}
        shown={shown}
        total={data.edges.length}
        onChange={setThreshold}
      />
      <div className="lambda-graph-canvas">
        {data.edges.length === 0 ? (
          <p className="lambda-graph-status">{t('graph.empty')}</p>
        ) : (
          <GraphPlot
            data={data}
            threshold={active}
            selection={selection}
            onSelect={selectWell}
          />
        )}
      </div>
      <p className="lambda-graph-hint">{t('graph.hint')}</p>
      <div className="lambda-graph-panels">
        <GroupLegend data={data} />
        <MetaPanel meta={data.meta} />
        {selection !== null && (
          <SelectionPanel selection={selection} onClear={() => selectWell(null)} />
        )}
      </div>
    </section>
  );
};
