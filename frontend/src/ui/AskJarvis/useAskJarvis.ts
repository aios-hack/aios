import { useCallback } from 'react';
import { useOptionalJarvis } from '../../jarvis/JarvisContext';

export const useAskJarvis = (): ((question: string) => void) | null => {
  const jarvis = useOptionalJarvis();

  const ask = useCallback(
    (question: string) => {
      if (jarvis === null || question.length === 0) {
        return;
      }
      jarvis.open();
      jarvis.askQuestion(question);
    },
    [jarvis]
  );

  return jarvis === null ? null : ask;
};
