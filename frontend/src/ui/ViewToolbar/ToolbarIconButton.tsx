import type { ReactNode } from 'react';
import './ToolbarIconButton.css';

interface ToolbarIconButtonProps {
  refCallback: (node: HTMLButtonElement | null) => void;
  open: boolean;
  label: string;
  guide?: string;
  onClick: () => void;
  children: ReactNode;
}

export const ToolbarIconButton = ({
  refCallback,
  open,
  label,
  guide,
  onClick,
  children
}: ToolbarIconButtonProps) => (
  <button
    ref={refCallback}
    type="button"
    className="toolbar-icon-button"
    aria-expanded={open}
    aria-haspopup="dialog"
    aria-label={label}
    data-guide={guide}
    onClick={onClick}
  >
    {children}
  </button>
);
