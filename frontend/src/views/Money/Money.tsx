import { useT } from '../../i18n/I18nContext';
import { useConsole } from '../../state/ConsoleContext';
import { MoneyComparison } from './MoneyComparison';
import { MoneyConstraints } from './MoneyConstraints';
import { MoneyRank } from './MoneyRank';
import './Money.css';

export const Money = () => {
  const t = useT();
  const { view } = useConsole();

  return (
    <div className="money" data-testid="money-workspace">
      {view === 'rank' && <MoneyRank />}
      {view === 'comparison' && <MoneyComparison />}
      {view === 'constraints' && <MoneyConstraints />}
      {view !== 'rank' && view !== 'comparison' && view !== 'constraints' && (
        <p>{t('view.label')}</p>
      )}
    </div>
  );
};
