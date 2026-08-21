import { DiamondIcon } from '@phosphor-icons/react';
import { Popover } from '../Popover';
import { ToolbarIconButton } from '../ViewToolbar';
import { Legend, type LegendProps } from './Legend';

interface LegendPopoverProps extends LegendProps {
  triggerLabel: string;
}

export const LegendPopover = ({ triggerLabel, ...legend }: LegendPopoverProps) => (
  <Popover
    label={legend.title}
    trigger={({ ref, open, onClick }) => (
      <ToolbarIconButton refCallback={ref} open={open} label={triggerLabel} onClick={onClick}>
        <DiamondIcon size={14} weight="bold" aria-hidden="true" />
      </ToolbarIconButton>
    )}
  >
    <Legend {...legend} />
  </Popover>
);
