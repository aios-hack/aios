import { CaretDownIcon } from '@phosphor-icons/react';
import { useEffect, useRef, useState } from 'react';
import { useDataset } from '../../data';
import { useI18n } from '../../i18n/I18nContext';
import { DEFAULT_SCENARIO_ID, useOptionalScenario } from '../../state/ScenarioContext';
import { useProvenance } from '../../state/ProvenanceContext';
import { TrustBoard } from './TrustBoard';
import { buildVerdict } from './verdict';
import './StatusChip.css';

export const StatusChip = () => {
  const { t } = useI18n();
  const { activeId } = useOptionalScenario();
  const source = useProvenance();
  const index = useDataset('scenarios');
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const popoverRef = useRef<HTMLDivElement | null>(null);

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

  const verdict = buildVerdict(active, source);
  const label = t(
    verdict.labelKey,
    verdict.labelParams?.field
      ? { ...verdict.labelParams, field: t(verdict.labelParams.field as string) }
      : verdict.labelParams
  );

  return (
    <div className="status-chip-wrap">
      <button
        ref={triggerRef}
        type="button"
        className="status-chip"
        data-level={verdict.level}
        aria-expanded={open}
        aria-label={t('trust.chip.label')}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="status-chip-dot" aria-hidden="true" />
        <span className="status-chip-text">{label}</span>
        <CaretDownIcon size={12} weight="bold" aria-hidden="true" />
      </button>
      {open && (
        <div
          ref={popoverRef}
          className="status-chip-popover"
          role="dialog"
          aria-label={t('trust.title')}
        >
          <TrustBoard />
        </div>
      )}
    </div>
  );
};
