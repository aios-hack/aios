import { InfoIcon } from '@phosphor-icons/react';
import { useId, useLayoutEffect, useRef, useState, type CSSProperties } from 'react';
import { createPortal } from 'react-dom';
import './InfoHint.css';

const GAP = 10;
const WIDTH = 280;
const EDGE = 12;

interface InfoHintProps {
  text: string;
  label: string;
}

export const InfoHint = ({ text, label }: InfoHintProps) => {
  const [open, setOpen] = useState(false);
  const [style, setStyle] = useState<CSSProperties | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const id = useId();

  useLayoutEffect(() => {
    if (!open || triggerRef.current === null) {
      return;
    }
    const rect = triggerRef.current.getBoundingClientRect();
    const half = WIDTH / 2;
    const centre = rect.left + rect.width / 2;
    const left = Math.min(
      Math.max(centre - half, EDGE),
      window.innerWidth - WIDTH - EDGE
    );
    const above = rect.top > 160;
    setStyle({
      left,
      width: WIDTH,
      top: above ? undefined : rect.bottom + GAP,
      bottom: above ? window.innerHeight - rect.top + GAP : undefined
    });
  }, [open]);

  return (
    <span className="info-hint">
      <button
        ref={triggerRef}
        type="button"
        className="info-hint-trigger"
        aria-label={label}
        aria-expanded={open}
        aria-describedby={open ? id : undefined}
        onClick={() => setOpen((value) => !value)}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
      >
        <InfoIcon size={15} weight="duotone" aria-hidden="true" />
      </button>
      {open &&
        style !== null &&
        createPortal(
          <span className="info-hint-bubble" id={id} role="tooltip" style={style}>
            {text}
          </span>,
          document.body
        )}
    </span>
  );
};
