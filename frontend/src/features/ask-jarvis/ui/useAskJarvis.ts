import { useCallback } from 'react';
import { useOptionalJarvisSession } from '@/jarvis';

export const useAskJarvis = (): ((question: string) => void) | null => {
  const jarvis = useOptionalJarvisSession();

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
