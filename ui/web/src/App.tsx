import { useState } from 'react';
import { useI18n } from './i18n/I18nContext';
import { HeaderControls } from './ui/HeaderControls';
import { SyntheticBanner } from './ui/SyntheticBanner';
import { TabBar } from './ui/TabBar';
import { FieldMap } from './views/FieldMap';
import { LambdaGraph } from './views/LambdaGraph';
import { NpvRank } from './views/NpvRank';
import { Scenarios } from './views/Scenarios';
import { Timeline } from './views/Timeline';
import { WellCard } from './views/WellCard';

type ViewId = 'graph' | 'map' | 'steps' | 'npv' | 'scenarios';

const VIEWS: ViewId[] = ['graph', 'map', 'steps', 'npv', 'scenarios'];

export const App = () => {
  const { t } = useI18n();
  const [view, setView] = useState<ViewId>('graph');

  return (
    <div className="app">
      <header className="app-header">
        <div className="app-identity">
          <span className="app-eyebrow">{t('app.eyebrow')}</span>
          <h1 className="app-title">
            <span className="app-title-accent">AIOS</span> {t('app.title')}
          </h1>
          <p className="app-subtitle">{t('app.subtitle')}</p>
        </div>
        <HeaderControls />
      </header>
      <SyntheticBanner />
      <TabBar
        ids={VIEWS}
        active={view}
        label={t('tabs.label')}
        renderLabel={(id) => t(`tab.${id}`)}
        onSelect={setView}
      />
      <main
        key={view}
        className="app-main app-view-enter"
        id={`panel-${view}`}
        role="tabpanel"
        aria-labelledby={`tab-${view}`}
        tabIndex={-1}
      >
        <h2 className="app-view-title">{t(`${view}.title`)}</h2>
        {view === 'graph' && <LambdaGraph />}
        {view === 'map' && <FieldMap />}
        {view === 'steps' && <Timeline />}
        {view === 'npv' && <NpvRank />}
        {view === 'scenarios' && <Scenarios />}
      </main>
      <WellCard />
    </div>
  );
};
