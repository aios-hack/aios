import { InfoIcon } from '@phosphor-icons/react';
import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties
} from 'react';
import { createPortal } from 'react-dom';
import './InfoHint.css';

const GAP = 10;
const WIDTH = 280;
const EDGE = 12;
const LINGER = 120;

interface InfoHintProps {
  text: string;
  label: string;
}

export const InfoHint = ({ text, label }: InfoHintProps) => {
  const [open, setOpen] = useState(false);
  const [style, setStyle] = useState<CSSProperties | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const closeTimer = useRef<number | null>(null);
  const dismissed = useRef(false);
  const id = useId();

  const cancelClose = useCallback(() => {
    if (closeTimer.current !== null) {
      window.clearTimeout(closeTimer.current);
      closeTimer.current = null;
    }
  }, []);

  const scheduleClose = useCallback(() => {
    cancelClose();
    closeTimer.current = window.setTimeout(() => setOpen(false), LINGER);
  }, [cancelClose]);

  const closeNow = useCallback(() => {
    cancelClose();
    setOpen(false);
  }, [cancelClose]);

  useEffect(() => cancelClose, [cancelClose]);

  useEffect(() => {
    if (!open) {
      return;
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation();
        dismissed.current = true;
        closeNow();
        triggerRef.current?.focus();
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [open, closeNow]);

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
        onClick={() => {
          dismissed.current = false;
          cancelClose();
          setOpen((value) => !value);
        }}
        onMouseEnter={() => {
          dismissed.current = false;
          cancelClose();
          setOpen(true);
        }}
        onMouseLeave={scheduleClose}
        onFocus={() => {
          if (dismissed.current) {
            return;
          }
          cancelClose();
          setOpen(true);
        }}
        onBlur={() => {
          dismissed.current = false;
          closeNow();
        }}
      >
        <InfoIcon size={15} weight="duotone" aria-hidden="true" />
      </button>
      {open &&
        style !== null &&
        createPortal(
          <span
            className="info-hint-bubble"
            id={id}
            role="tooltip"
            style={style}
            onMouseEnter={cancelClose}
            onMouseLeave={scheduleClose}
          >
            {text}
          </span>,
          document.body
        )}
    </span>
  );
};
