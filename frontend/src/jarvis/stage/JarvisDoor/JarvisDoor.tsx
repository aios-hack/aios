import { CubeIcon } from '@phosphor-icons/react';
import { useT } from '@/shared/i18n/I18nContext';
import { useJarvisSessionContext } from '@/jarvis/provider/contexts';
import './JarvisDoor.css';

export const DOOR_SLOT_ID = 'jarvis-door-slot';

export const JarvisDoor = () => {
  const t = useT();
  const { close } = useJarvisSessionContext();

  return (
    <button
      type="button"
      className="jarvis-door"
      aria-label={t('jarvis-stage.closeLabel')}
      aria-keyshortcuts="Escape"
      onClick={close}
    >
      <span className="jarvis-door-slot" id={DOOR_SLOT_ID} aria-hidden="true">
        <CubeIcon size={22} weight="light" aria-hidden="true" />
      </span>
      <span className="jarvis-door-name">{t('jarvis-stage.doorLabel')}</span>
      <kbd className="jarvis-door-key">Esc</kbd>
    </button>
  );
};
