import { useState } from 'react';
import { useDocumentTitle } from './app/useDocumentTitle';
import { useI18n } from './i18n/I18nContext';
import { BrandLogo } from './ui/BrandLogo';
import { HeaderControls } from './ui/HeaderControls';
import { ScenarioBadge } from './ui/ScenarioBadge';
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
  const { t, lang } = useI18n();
  const [view, setView] = useState<ViewId>('graph');
  useDocumentTitle(t(`tab.${view}`), t('app.documentTitle'), lang);

  return (
    <div className="app">
      <header className="app-header">
        <BrandLogo />
        <div className="app-identity">
          <h1 className="app-title">
            <span className="app-title-accent">AIOS</span>
            <span className="app-title-rest">{t('app.title')}</span>
          </h1>
          <p className="app-subtitle">
            {t('app.subtitle')}
            <SyntheticBanner />
          </p>
        </div>
        <HeaderControls />
      </header>
      <div className="app-navigation">
        <TabBar
          ids={VIEWS}
          active={view}
          label={t('tabs.label')}
          renderLabel={(id) => t(`tab.${id}`)}
          onSelect={setView}
        />
        <ScenarioBadge />
      </div>
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
