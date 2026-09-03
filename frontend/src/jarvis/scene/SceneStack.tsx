import type { CSSProperties } from 'react';
import { useT } from '../../i18n/I18nContext';
import type { Scene } from '../scenes';
import './SceneStack.css';

interface SceneStackProps {
  scenes: readonly Scene[];
  activeIndex: number;
  onSelect: (index: number) => void;
}

export const stackDepth = (index: number, activeIndex: number): number =>
  Math.max(0, activeIndex - index);

export const SceneStack = ({ scenes, activeIndex, onSelect }: SceneStackProps) => {
  const t = useT();
  const behind = scenes.slice(0, Math.max(0, activeIndex));
  if (behind.length === 0) {
    return null;
  }

  return (
    <ol
      className="jarvis-stack"
      aria-label={t('jarvis.stackLabel')}
      title={t('jarvis.stackHint')}
    >
      {behind.map((scene, index) => (
        <li
          className="jarvis-stack-item"
          key={scene.id}
          style={{ '--stack-depth': `${stackDepth(index, activeIndex)}` } as CSSProperties}
        >
          <button type="button" className="jarvis-stack-button" onClick={() => onSelect(index)}>
            {scene.question}
          </button>
        </li>
      ))}
    </ol>
  );
};
