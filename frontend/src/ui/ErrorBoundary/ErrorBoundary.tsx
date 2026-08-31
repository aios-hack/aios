import { Component, type ErrorInfo, type ReactNode } from 'react';
import { useFallbackT } from '../../i18n/I18nContext';
import { ViewStatus } from '../ViewStatus';

interface ErrorBoundaryProps {
  children: ReactNode;
  silent?: boolean;
}

interface ErrorBoundaryState {
  failed: boolean;
}

const ErrorFallback = () => {
  const t = useFallbackT();
  return <ViewStatus kind="error" title={t('boundary.title')} hint={t('boundary.hint')} />;
};

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { failed: false };

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('ErrorBoundary caught a render error', error, info.componentStack);
  }

  render(): ReactNode {
    if (this.state.failed) {
      if (this.props.silent === true) {
        return null;
      }
      return <ErrorFallback />;
    }
    return this.props.children;
  }
}
