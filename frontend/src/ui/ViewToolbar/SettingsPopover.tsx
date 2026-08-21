import { GearIcon } from '@phosphor-icons/react';
import type { ReactNode } from 'react';
import { Popover } from '../Popover';
import { ToolbarIconButton } from './ToolbarIconButton';
import './SettingsPopover.css';

interface SettingsPopoverProps {
  label: string;
  title: string;
  children: ReactNode;
}

export const SettingsPopover = ({ label, title, children }: SettingsPopoverProps) => (
  <Popover
    label={title}
    trigger={({ ref, open, onClick }) => (
      <ToolbarIconButton refCallback={ref} open={open} label={label} onClick={onClick}>
        <GearIcon size={14} weight="bold" aria-hidden="true" />
      </ToolbarIconButton>
    )}
  >
    <p className="settings-popover-title">{title}</p>
    <div className="settings-popover-body">{children}</div>
  </Popover>
);
