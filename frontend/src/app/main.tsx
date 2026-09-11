import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from '@/app/App/App';
import { AppProviders } from '@/app/providers';
import { JarvisProvider } from '@/jarvis/provider/JarvisProvider';
import { JarvisStage } from '@/jarvis/stage/JarvisStage/JarvisStage';
import '@/jarvis/actions/lib/spotlight.css';
import '@/shared/theme/tokens.css';
import '@/app/styles/styles.css';

const container = document.getElementById('root');
if (!container) {
  throw new Error('root element not found');
}

createRoot(container).render(
  <StrictMode>
    <AppProviders>
      <JarvisProvider>
        <JarvisStage>
          <App />
        </JarvisStage>
      </JarvisProvider>
    </AppProviders>
  </StrictMode>
);
