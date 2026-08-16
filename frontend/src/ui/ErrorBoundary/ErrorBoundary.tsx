import { Component, type ErrorInfo, type ReactNode } from 'react';
import { useT } from '../../i18n/I18nContext';
import { ViewStatus } from '../ViewStatus';

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  message: string | null;
}

const ErrorFallback = ({ message }: { message: string }) => {
  const t = useT();
  return <ViewStatus kind="error" title={t('boundary.title')} hint={t('boundary.hint', { message })} />;
};

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { message: null };

  static getDerivedStateFromError(error: unknown): ErrorBoundaryState {
    return { message: error instanceof Error ? error.message : String(error) };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('ErrorBoundary caught a render error', error, info.componentStack);
  }

  render(): ReactNode {
    if (this.state.message !== null) {
      return <ErrorFallback message={this.state.message} />;
    }
    return this.props.children;
  }
}
