import { useEffect, useRef, useState } from 'react';
import { useDataset } from '../../data';
import { useI18n } from '../../i18n/I18nContext';
import { DEFAULT_SCENARIO_ID, useOptionalScenario } from '../../state/ScenarioContext';
import { TrustBoard } from './TrustBoard';
import { buildVerdict } from './verdict';
import './StatusChip.css';

export const StatusChip = () => {
  const { t } = useI18n();
  const { activeId } = useOptionalScenario();
  const index = useDataset('scenarios');
  const [open, setOpen] = useState(false);
  const [mounted, setMounted] = useState(false);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const popoverRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (open) {
      setMounted(true);
      return;
    }
    const node = popoverRef.current;
    if (node === null) {
      setMounted(false);
      return;
    }
    let cancelled = false;
    const frame = requestAnimationFrame(() => {
      const animations =
        typeof node.getAnimations === 'function' ? node.getAnimations() : [];
      if (animations.length === 0) {
        setMounted(false);
        return;
      }
      Promise.allSettled(animations.map((animation) => animation.finished)).then(() => {
        if (!cancelled) {
          setMounted(false);
        }
      });
    });
    return () => {
      cancelled = true;
      cancelAnimationFrame(frame);
    };
  }, [open]);

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
        popoverRef.current?.contains(target) === true ||
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

  if (index.status !== 'ready') {
    return null;
  }

  const entries = index.data.scenarios;
  const active =
    entries.find((entry) => entry.id === activeId) ??
    (activeId === DEFAULT_SCENARIO_ID ? entries[0] : undefined);

  if (!active) {
    return null;
  }

  const verdict = buildVerdict(active);
  const label = t(
    verdict.labelKey,
    verdict.labelParams?.field
      ? { ...verdict.labelParams, field: t(verdict.labelParams.field as string) }
      : verdict.labelParams
  );

  return (
    <div className="icon-island status-chip-wrap">
      <button
        ref={triggerRef}
        type="button"
        className="icon-button status-chip"
        data-guide="overview-trustboard"
        data-level={verdict.level}
        aria-expanded={open}
        aria-label={t('trust.chip.label')}
        title={label}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="icon-button-glyph" aria-hidden="true">
          ?
        </span>
        <span className="visually-hidden">{label}</span>
      </button>
      {mounted && (
        <div
          ref={popoverRef}
          className="status-chip-popover"
          data-state={open ? 'open' : 'closing'}
          role="dialog"
          aria-label={t('trust.title')}
        >
          <TrustBoard />
        </div>
      )}
    </div>
  );
};
