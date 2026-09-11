import type { CSSProperties } from 'react';
import type { Scene } from '@/jarvis/model/scenes';
import './SceneStack.css';

interface SceneStackProps {
  scenes: readonly Scene[];
  activeIndex: number;
}

export const MAX_DEPTH = 4;

export const stackDepth = (index: number, activeIndex: number): number =>
  Math.max(0, activeIndex - index);

export const SceneStack = ({ scenes, activeIndex }: SceneStackProps) => {
  const behind = scenes.slice(Math.max(0, activeIndex - MAX_DEPTH), Math.max(0, activeIndex));
  if (behind.length === 0) {
    return null;
  }
  const base = Math.max(0, activeIndex - behind.length);

  return (
    <div className="jarvis-stack" aria-hidden="true">
      {behind.map((scene, index) => (
        <span
          className="jarvis-stack-plate"
          key={scene.id}
          style={{ '--stack-depth': `${stackDepth(base + index, activeIndex)}` } as CSSProperties}
        />
      ))}
    </div>
  );
};
