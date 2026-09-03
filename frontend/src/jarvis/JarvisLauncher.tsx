import { useT } from '../i18n/I18nContext';
import { useOptionalJarvis } from './JarvisContext';
import { EnergySphere } from './sphere/EnergySphere';
import './JarvisLauncher.css';

export const LAUNCHER_SLOT_ID = 'jarvis-launcher-slot';

export const JarvisLauncher = () => {
  const t = useT();
  const jarvis = useOptionalJarvis();
  if (jarvis === null) {
    return null;
  }
  const { open, setHovering, sphereState, audioLevel, visible } = jarvis;

  return (
    <button
      type="button"
      className="jarvis-launcher"
      aria-label={t('jarvis.openLabel')}
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
      <span className="jarvis-launcher-name">{t('jarvis.name')}</span>
    </button>
  );
};
