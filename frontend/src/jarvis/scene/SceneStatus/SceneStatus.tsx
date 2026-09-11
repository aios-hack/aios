import { useT } from '@/shared/i18n/I18nContext';
import { translateOr } from '@/jarvis/i18nFallback';
import { useOptionalJarvisSession } from '@/jarvis/provider/contexts';
import type { Scene } from '@/jarvis/model/scenes';
import type { JarvisStatusState } from '@/jarvis/transport/events';
import './SceneStatus.css';

interface SceneStatusProps {
  status: JarvisStatusState | null;
  tool: string | null;
  micOpen: boolean;
  scene: Scene | null;
}

export const SceneStatus = ({ status, tool, micOpen, scene }: SceneStatusProps) => {
  const t = useT();
  const jarvis = useOptionalJarvisSession();
  const failure = scene?.error ?? null;

  if (failure !== null) {
    return (
      <p className="jarvis-status" role="alert" data-kind="error">
        {translateOr(t, `jarvis-screen.error.${failure.code}`, 'jarvis-screen.error.unknown')}
        {jarvis === null ? null : (
          <button type="button" className="jarvis-status-retry" onClick={jarvis.retry}>
            {t('jarvis-screen.retry')}
          </button>
        )}
      </p>
    );
  }

  const label = micOpen
    ? t('jarvis-voice.listening')
    : status === 'thinking'
      ? t('jarvis-screen.thinking')
      : status === 'tool'
        ? t('jarvis-screen.toolRunning', { tool: tool ?? '' })
        : status === 'composing'
          ? t('jarvis-screen.composing')
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
