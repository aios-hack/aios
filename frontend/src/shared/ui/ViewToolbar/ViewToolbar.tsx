import type { ReactNode } from 'react';
import './ViewToolbar.css';

interface ViewToolbarProps {
  left?: ReactNode;
  center?: ReactNode;
  right?: ReactNode;
}

export const ViewToolbar = ({ left, center, right }: ViewToolbarProps) => (
  <div className="view-toolbar">
    <div className="view-toolbar-group view-toolbar-left">{left}</div>
    <div className="view-toolbar-group view-toolbar-center">{center}</div>
    <div className="view-toolbar-group view-toolbar-right">{right}</div>
  </div>
);
