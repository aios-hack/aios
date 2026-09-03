import { useT } from '../../i18n/I18nContext';
import './Suggestions.css';

interface SuggestionsProps {
  items: readonly string[];
  onPick: (text: string) => void;
}

export const Suggestions = ({ items, onPick }: SuggestionsProps) => {
  const t = useT();
  if (items.length === 0) {
    return null;
  }
  return (
    <ul className="jarvis-suggestions" aria-label={t('jarvis.suggestionsLabel')}>
      {items.map((text) => (
        <li key={text}>
          <button type="button" className="jarvis-suggestion" onClick={() => onPick(text)}>
            {text}
          </button>
        </li>
      ))}
    </ul>
  );
};
