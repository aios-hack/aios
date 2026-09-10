import { useEffect, useState } from 'react';

const STAGE_SELECTOR = '.jarvis-stage';

export const stageIsSettled = (doc: Document): boolean => {
  const stage = doc.querySelector(STAGE_SELECTOR);
  return stage === null || stage.getAttribute('data-phase') === 'closed';
};

export const useStageSettled = (): boolean => {
  const [settled, setSettled] = useState(() =>
    typeof document === 'undefined' ? true : stageIsSettled(document)
  );

  useEffect(() => {
    const stage = document.querySelector(STAGE_SELECTOR);
    if (stage === null || typeof MutationObserver !== 'function') {
      return;
    }
    const sync = () => setSettled(stage.getAttribute('data-phase') === 'closed');
    sync();
    const observer = new MutationObserver(sync);
    observer.observe(stage, { attributes: true, attributeFilter: ['data-phase'] });
    return () => observer.disconnect();
  }, []);

  return settled;
};
