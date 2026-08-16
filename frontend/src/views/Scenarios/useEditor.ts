import { useCallback, useMemo, useState } from 'react';
import type { ConstraintsDoc } from '../../api/types';
import {
  emptyEditorState,
  nextKey,
  toDocument,
  validateEditor,
  type EditorState,
  type FieldError,
  type OutageRow,
  type PairRow,
  type YearRow,
  type YearSection
} from './constraints';

interface EditorApi {
  state: EditorState;
  errors: FieldError[];
  document: ConstraintsDoc;
  setState: (state: EditorState) => void;
  changeYear: (section: YearSection, key: string, field: 'year' | 'value', value: string) => void;
  addYear: (section: YearSection) => void;
  removeYear: (section: YearSection, key: string) => void;
  changeOutage: (key: string, field: 'well' | 'from' | 'to', value: string) => void;
  addOutage: () => void;
  removeOutage: (key: string) => void;
  changePair: (key: string, field: 'name' | 'value', value: string) => void;
  addPair: () => void;
  removePair: (key: string) => void;
  reset: () => void;
}

const patch = <T extends { key: string }>(rows: T[], key: string, field: string, value: string): T[] =>
  rows.map((row) => (row.key === key ? { ...row, [field]: value } : row));

export const useEditor = (nIntervals: number): EditorApi => {
  const [state, setState] = useState<EditorState>(emptyEditorState);

  const errors = useMemo(() => validateEditor(state, nIntervals), [state, nIntervals]);
  const document = useMemo(() => toDocument(state), [state]);

  const changeYear = useCallback(
    (section: YearSection, key: string, field: 'year' | 'value', value: string) =>
      setState((current) => ({
        ...current,
        sections: {
          ...current.sections,
          [section]: patch<YearRow>(current.sections[section], key, field, value)
        }
      })),
    []
  );

  const addYear = useCallback(
    (section: YearSection) =>
      setState((current) => ({
        ...current,
        sections: {
          ...current.sections,
          [section]: [
            ...current.sections[section],
            { key: nextKey(section), year: '', value: '' }
          ]
        }
      })),
    []
  );

  const removeYear = useCallback(
    (section: YearSection, key: string) =>
      setState((current) => ({
        ...current,
        sections: {
          ...current.sections,
          [section]: current.sections[section].filter((row) => row.key !== key)
        }
      })),
    []
  );

  const changeOutage = useCallback(
    (key: string, field: 'well' | 'from' | 'to', value: string) =>
      setState((current) => ({
        ...current,
        outages: patch<OutageRow>(current.outages, key, field, value)
      })),
    []
  );

  const addOutage = useCallback(
    () =>
      setState((current) => ({
        ...current,
        outages: [...current.outages, { key: nextKey('outage'), well: '', from: '', to: '' }]
      })),
    []
  );

  const removeOutage = useCallback(
    (key: string) =>
      setState((current) => ({
        ...current,
        outages: current.outages.filter((row) => row.key !== key)
      })),
    []
  );

  const changePair = useCallback(
    (key: string, field: 'name' | 'value', value: string) =>
      setState((current) => ({
        ...current,
        infrastructure: patch<PairRow>(current.infrastructure, key, field, value)
      })),
    []
  );

  const addPair = useCallback(
    () =>
      setState((current) => ({
        ...current,
        infrastructure: [
          ...current.infrastructure,
          { key: nextKey('pair'), name: '', value: '' }
        ]
      })),
    []
  );

  const removePair = useCallback(
    (key: string) =>
      setState((current) => ({
        ...current,
        infrastructure: current.infrastructure.filter((row) => row.key !== key)
      })),
    []
  );

  const reset = useCallback(() => setState(emptyEditorState()), []);

  return {
    state,
    errors,
    document,
    setState,
    changeYear,
    addYear,
    removeYear,
    changeOutage,
    addOutage,
    removeOutage,
    changePair,
    addPair,
    removePair,
    reset
  };
};
