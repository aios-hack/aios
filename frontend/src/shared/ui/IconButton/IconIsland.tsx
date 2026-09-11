import type { ReactNode } from 'react';
import './IconButton.css';

interface IconIslandProps {
  className?: string;
  children: ReactNode;
}

export const IconIsland = ({ className, children }: IconIslandProps) => (
  <div className={className === undefined ? 'icon-island' : `icon-island ${className}`}>
    {children}
  </div>
);
