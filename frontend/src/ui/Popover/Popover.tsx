import { useEffect, useRef, useState, type ReactNode } from 'react';
import './Popover.css';

interface PopoverProps {
  trigger: (props: {
    ref: (node: HTMLButtonElement | null) => void;
    open: boolean;
    onClick: () => void;
  }) => ReactNode;
  label: string;
  align?: 'start' | 'end';
  children: ReactNode;
}

export const Popover = ({ trigger, label, align = 'end', children }: PopoverProps) => {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) {
      return;
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setOpen(false);
        triggerRef.current?.focus();
      }
    };
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (
        panelRef.current?.contains(target) === true ||
        triggerRef.current?.contains(target) === true
      ) {
        return;
      }
      setOpen(false);
    };
    window.addEventListener('keydown', onKeyDown);
    window.addEventListener('pointerdown', onPointerDown);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('pointerdown', onPointerDown);
    };
  }, [open]);

  return (
    <div className="popover-wrap">
      {trigger({
        ref: (node) => {
          triggerRef.current = node;
        },
        open,
        onClick: () => setOpen((value) => !value)
      })}
      {open && (
        <div
          ref={panelRef}
          className="popover-panel"
          data-align={align}
          role="dialog"
          aria-label={label}
        >
          {children}
        </div>
      )}
    </div>
  );
};
