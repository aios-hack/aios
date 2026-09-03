import { useT } from '../../i18n/I18nContext';
import { routeAction, type ConsoleAction } from '../actions/consoleAction';
import { readGuide } from './cardPayloads';
import { EmptyPayload } from './EmptyPayload';
import './GuideCard.css';

interface GuideCardProps {
  payload: unknown;
  onOpen: (action: ConsoleAction) => void;
}

export const GuideCard = ({ payload, onOpen }: GuideCardProps) => {
  const t = useT();
  const guide = readGuide(payload);
  if (guide === null) {
    return <EmptyPayload />;
  }

  return (
    <div className="jarvis-guide">
      <p className="jarvis-guide-block">
        <span className="jarvis-guide-label">{t('jarvis.guideWhat')}</span>
        {guide.what}
      </p>
      {guide.how_to_read.length === 0 ? null : (
        <p className="jarvis-guide-block">
          <span className="jarvis-guide-label">{t('jarvis.guideHowToRead')}</span>
          {guide.how_to_read}
        </p>
      )}
      {guide.controls.length === 0 ? null : (
        <div className="jarvis-guide-controls">
          <p className="jarvis-guide-label">{t('jarvis.guideControls')}</p>
          <ul>
            {guide.controls.map((control) => (
              <li key={control.label}>
                <span>{control.label}</span>
                {control.hotkey === null ? null : (
                  <kbd className="jarvis-guide-hotkey">{control.hotkey}</kbd>
                )}
                <button
                  type="button"
                  className="jarvis-guide-open"
                  onClick={() =>
                    onOpen(routeAction(guide.workspace, guide.view, control.spotlight))
                  }
                >
                  {t('jarvis.open')}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
      {guide.questions.length === 0 ? null : (
        <p className="jarvis-guide-questions">
          <span className="jarvis-guide-label">{t('jarvis.guideQuestions')}</span>
          {guide.questions.join(' · ')}
        </p>
      )}
    </div>
  );
};
