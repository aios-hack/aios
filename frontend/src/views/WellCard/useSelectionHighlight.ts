import { useMemo } from 'react';
import type { GraphFile } from '../../api/types';
import { dataOf, useDataset } from '../../data';
import { useTimeline } from '../../state/TimelineContext';
import { groupColor } from '../../theme/tokens';
import { connectivityOf, neighbourThreshold } from './neighbours';

export type HighlightState = 'selected' | 'neighbour' | 'group' | 'faded' | 'plain';

export interface SelectionHighlight {
  well: string | null;
  stateOf: (well: string) => HighlightState;
  groupOf: (well: string) => string | null;
  groupColorOf: (well: string) => string | null;
}

const groupsOf = (graph: GraphFile | null): Map<string, string> => {
  const map = new Map<string, string>();
  if (graph === null) {
    return map;
  }
  for (const node of graph.nodes) {
    if (node.group !== null) {
      map.set(node.id, node.group);
    }
  }
  return map;
};

export const useSelectionHighlight = (): SelectionHighlight => {
  const { selectedWell } = useTimeline();
  const graphState = useDataset('graph');
  const graph = dataOf(graphState);

  return useMemo(() => {
    const groups = groupsOf(graph);
    const order = new Map((graph?.groups ?? []).map((group, index) => [group.id, index]));
    const groupOf = (well: string) => groups.get(well) ?? null;
    const groupColorOf = (well: string) => {
      const group = groupOf(well);
      return group === null ? null : groupColor(order.get(group) ?? 0);
    };

    if (selectedWell === null || graph === null) {
      return {
        well: selectedWell,
        stateOf: () => 'plain' as HighlightState,
        groupOf,
        groupColorOf
      };
    }

    const connectivity = connectivityOf(
      selectedWell,
      graph,
      neighbourThreshold(graph.edges)
    );
    const neighbours = new Set(connectivity.neighbours.map((item) => item.well));
    const group = connectivity.group;
    const members = new Set<string>();
    if (group !== null) {
      const found = graph.groups.find((item) => item.id === group);
      for (const member of found?.wells ?? []) {
        members.add(member);
      }
    }

    const stateOf = (well: string): HighlightState => {
      if (well === selectedWell) {
        return 'selected';
      }
      if (neighbours.has(well)) {
        return 'neighbour';
      }
      if (members.has(well)) {
        return 'group';
      }
      return 'faded';
    };

    return { well: selectedWell, stateOf, groupOf, groupColorOf };
  }, [graph, selectedWell]);
};
