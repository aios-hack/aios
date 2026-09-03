import { useT } from '../../i18n/I18nContext';
import { translateOr } from '../i18nFallback';
import type { Scene } from '../scenes';
import './Caption.css';

export const Caption = ({ scene }: { scene: Scene | null }) => {
  const t = useT();
  if (scene === null) {
    return null;
  }
  const text = scene.caption ?? scene.captionDraft;
  const printing = scene.caption === null && text.length > 0;

  return (
    <div className="jarvis-caption">
      <p
        className="jarvis-caption-text"
        aria-live="polite"
        aria-label={t('jarvis.captionLabel')}
        data-printing={printing ? 'true' : undefined}
      >
        {text}
      </p>
      {scene.warnings.map((warning) => (
        <p className="jarvis-caption-warning" key={warning.code}>
          <span className="jarvis-caption-warning-label">{t('jarvis.warningLabel')}</span>
          {translateOr(t, `jarvis.warning.${warning.code}`, 'jarvis.warning.unknown')}
        </p>
      ))}
    </div>
  );
};
