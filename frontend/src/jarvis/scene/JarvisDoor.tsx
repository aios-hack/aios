import { CubeIcon } from '@phosphor-icons/react';
import { useT } from '../../i18n/I18nContext';
import { useJarvis } from '../JarvisContext';
import './JarvisDoor.css';

export const DOOR_SLOT_ID = 'jarvis-door-slot';

export const JarvisDoor = () => {
  const t = useT();
  const { close } = useJarvis();

  return (
    <button
      type="button"
      className="jarvis-door"
      aria-label={t('jarvis.closeLabel')}
      aria-keyshortcuts="Escape"
      onClick={close}
    >
      <span className="jarvis-door-slot" id={DOOR_SLOT_ID} aria-hidden="true">
        <CubeIcon size={22} weight="light" aria-hidden="true" />
      </span>
      <span className="jarvis-door-name">{t('jarvis.doorLabel')}</span>
      <kbd className="jarvis-door-key">Esc</kbd>
    </button>
  );
};
