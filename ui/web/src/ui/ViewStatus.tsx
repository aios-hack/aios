import type { ReactNode } from 'react';
import './ViewStatus.css';

export type StatusKind = 'loading' | 'error' | 'empty';

interface ViewStatusProps {
  kind: StatusKind;
  title: string;
  hint?: ReactNode;
}

export const ViewStatus = ({ kind, title, hint }: ViewStatusProps) => (
  <div
    className="view-status"
    data-kind={kind}
    role={kind === 'error' ? 'alert' : 'status'}
    aria-busy={kind === 'loading'}
  >
    {kind === 'loading' && <span className="view-status-spinner" aria-hidden="true" />}
    <p className="view-status-title">{title}</p>
    {hint !== undefined && <p className="view-status-hint">{hint}</p>}
  </div>
);
