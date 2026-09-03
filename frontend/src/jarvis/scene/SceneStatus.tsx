import { useT } from '../../i18n/I18nContext';
import { translateOr } from '../i18nFallback';
import type { Scene } from '../scenes';
import type { JarvisStatusState } from '../transport/events';
import './SceneStatus.css';

interface SceneStatusProps {
  status: JarvisStatusState | null;
  tool: string | null;
  micOpen: boolean;
  scene: Scene | null;
}

export const SceneStatus = ({ status, tool, micOpen, scene }: SceneStatusProps) => {
  const t = useT();
  const failure = scene?.error ?? null;

  if (failure !== null) {
    return (
      <p className="jarvis-status" role="alert" data-kind="error">
        {translateOr(t, `jarvis.error.${failure.code}`, 'jarvis.error.unknown')}
      </p>
    );
  }

  const label = micOpen
    ? t('jarvis.listening')
    : status === 'thinking'
      ? t('jarvis.thinking')
      : status === 'tool'
        ? t('jarvis.toolRunning', { tool: tool ?? '' })
        : status === 'composing'
          ? t('jarvis.composing')
          : null;

  if (label === null) {
    return null;
  }

  return (
    <p className="jarvis-status" role="status" data-kind={micOpen ? 'listening' : 'busy'}>
      <span className="jarvis-status-dot" aria-hidden="true" />
      {label}
    </p>
  );
};
