import { useT } from '@/shared/i18n/I18nContext';
import { useRoute } from '@/shared/router/RouterProvider';
import { MoneyComparison } from '@/pages/money-comparison/MoneyComparison/MoneyComparison';
import { MoneyConstraints } from '@/pages/money-constraints/MoneyConstraints/MoneyConstraints';
import { MoneyRank } from '@/pages/money-rank/MoneyRank/MoneyRank';
import './Money.css';

export const Money = () => {
  const t = useT();
  const { view } = useRoute();

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
