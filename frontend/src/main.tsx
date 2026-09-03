import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';
import { I18nProvider } from './i18n/I18nContext';
import { JarvisProvider } from './jarvis/JarvisContext';
import { JarvisStage } from './jarvis/JarvisStage';
import { ConsoleProvider } from './state/ConsoleContext';
import { PlaybackProvider } from './state/PlaybackContext';
import { ProvenanceProvider } from './state/ProvenanceContext';
import { ScenarioProvider } from './state/ScenarioContext';
import { TimelineProvider } from './state/TimelineContext';
import { ThemeProvider } from './theme/ThemeContext';
import './jarvis/actions/spotlight.css';
import './theme/tokens.css';
import './styles.css';

const container = document.getElementById('root');
if (!container) {
  throw new Error('root element not found');
}

createRoot(container).render(
  <StrictMode>
    <ThemeProvider>
      <I18nProvider>
        <ScenarioProvider>
          <ProvenanceProvider>
            <TimelineProvider>
              <PlaybackProvider>
                <ConsoleProvider>
                  <JarvisProvider>
                    <JarvisStage>
                      <App />
                    </JarvisStage>
                  </JarvisProvider>
                </ConsoleProvider>
              </PlaybackProvider>
            </TimelineProvider>
          </ProvenanceProvider>
        </ScenarioProvider>
      </I18nProvider>
    </ThemeProvider>
  </StrictMode>
);
