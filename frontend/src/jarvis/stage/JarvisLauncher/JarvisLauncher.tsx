import { useT } from '@/shared/i18n/I18nContext';
import { useOptionalJarvisSphere, useOptionalJarvisSession } from '@/jarvis/provider/contexts';
import { EnergySphere } from '@/jarvis/sphere/EnergySphere/EnergySphere';
import './JarvisLauncher.css';

export const LAUNCHER_SLOT_ID = 'jarvis-launcher-slot';

export const JarvisLauncher = () => {
  const t = useT();
  const jarvis = useOptionalJarvisSession();
  const sphere = useOptionalJarvisSphere();
  if (jarvis === null || sphere === null) {
    return null;
  }
  const { setHovering, sphereState, audioLevel } = sphere;
  const { open, visible } = jarvis;

  return (
    <button
      type="button"
      className="jarvis-launcher"
      aria-label={t('jarvis-stage.openLabel')}
      aria-keyshortcuts="j"
      aria-expanded={visible}
      data-state={sphereState}
      onClick={open}
      onPointerEnter={() => setHovering(true)}
      onPointerLeave={() => setHovering(false)}
      onFocus={() => setHovering(true)}
      onBlur={() => setHovering(false)}
    >
      <span className="jarvis-launcher-slot" id={LAUNCHER_SLOT_ID} data-flying={visible}>
        {visible ? null : (
          <EnergySphere state={sphereState} audio={audioLevel} />
        )}
      </span>
      <span className="jarvis-launcher-name">{t('jarvis-stage.name')}</span>
    </button>
  );
};
