import { useLayoutEffect, useRef, useState } from 'react';
import type { TimelineStep, TimelineWellRow } from '../../api/types';
import { actualRate } from '../../data';
import { useI18n } from '../../i18n/I18nContext';
import { DASH, formatNumber, formatPercent, formatStepDate } from '../../ui/format';
import type { ChronoMetric } from './cells';
import { modeOf } from './cells';
import { readingText } from './readings';

const READOUT_WIDTH = 264;
const READOUT_OFFSET = 12;
const READOUT_FALLBACK_HEIGHT = 260;
const READOUT_INSET = 2;

export interface HoverTarget {
  well: string;
  column: number;
  x: number;
  y: number;
}

export interface ReadoutBounds {
  left: number;
  right: number;
  top: number;
  bottom: number;
}

interface ChronoTooltipProps {
  bounds: ReadoutBounds;
  target: HoverTarget;
  step: TimelineStep | undefined;
  row: TimelineWellRow | undefined;
  metric: ChronoMetric;
  npv: number | undefined;
  group: string | null | undefined;
  closing: boolean;
}

export interface ReadoutFact {
  key: string;
  label: string;
  value: string;
  measured: boolean;
}

export interface ReadoutPlacement {
  flipX: boolean;
  flipY: boolean;
  nudgeX: number;
  nudgeY: number;
  room: number;
}

export const readoutFlip = (
  target: HoverTarget,
  bounds: ReadoutBounds,
  height: number
): { flipX: boolean; flipY: boolean } => {
  const overflowsRight = target.x + READOUT_OFFSET + READOUT_WIDTH > bounds.right;
  const fitsLeft = target.x - READOUT_OFFSET - READOUT_WIDTH >= bounds.left;
  const overflowsBottom = target.y + READOUT_OFFSET + height > bounds.bottom;
  const fitsAbove = target.y - READOUT_OFFSET - height >= bounds.top;
  return {
    flipX: overflowsRight && fitsLeft,
    flipY: overflowsBottom && fitsAbove
  };
};

export const readoutRoom = (
  target: HoverTarget,
  bounds: ReadoutBounds,
  flipY: boolean
): number =>
  Math.max(0, (flipY ? target.y - bounds.top : bounds.bottom - target.y) - READOUT_OFFSET);

export const readoutPlacement = (
  target: HoverTarget,
  bounds: ReadoutBounds,
  height: number
): ReadoutPlacement => {
  const { flipX, flipY } = readoutFlip(target, bounds, height);
  const room = readoutRoom(target, bounds, flipY);
  const shown = Math.min(height, room);
  const left = flipX
    ? target.x - READOUT_OFFSET - READOUT_WIDTH
    : target.x + READOUT_OFFSET;
  const top = flipY ? target.y - READOUT_OFFSET - shown : target.y + READOUT_OFFSET;
  const nudgeX = Math.floor(
    Math.min(0, bounds.right - READOUT_INSET - (left + READOUT_WIDTH)) +
      Math.max(0, bounds.left + READOUT_INSET - left)
  );
  const nudgeY = Math.floor(
    Math.min(0, bounds.bottom - READOUT_INSET - (top + shown)) +
      Math.max(0, bounds.top + READOUT_INSET - top)
  );
  return { flipX, flipY, nudgeX, nudgeY, room };
};

const MISSING = { text: DASH, measured: false };

const measured = (text: string) => ({ text, measured: true });

export const ChronoTooltip = ({
  bounds,
  target,
  step,
  row,
  metric,
  npv,
  group,
  closing
}: ChronoTooltipProps) => {
  const { t, lang } = useI18n();
  const panel = useRef<HTMLDivElement | null>(null);
  const [height, setHeight] = useState(READOUT_FALLBACK_HEIGHT);

  useLayoutEffect(() => {
    const node = panel.current;
    if (node === null) {
      return;
    }
    const next = node.getBoundingClientRect().height;
    if (next > 0 && Math.abs(next - height) > 0.5) {
      setHeight(next);
    }
  });

  const live = row !== undefined && row.availability !== 'NOT_COMMISSIONED';
  const flowing = live && row.operating_status === 'OPEN';

  const number = (value: number | undefined, digits: number) =>
    value === undefined || !Number.isFinite(value) ? MISSING : measured(formatNumber(lang, value, digits));

  const share = (value: number | null | undefined) =>
    value === null || value === undefined || !Number.isFinite(value)
      ? MISSING
      : measured(formatPercent(lang, value));

  const facts: ReadoutFact[] = [
    {
      key: 'setpoint',
      ...(flowing ? number(row.setpoint, 1) : MISSING)
    },
    {
      key: 'actual',
      ...(flowing ? number(actualRate(row), 1) : MISSING)
    },
    {
      key: 'ratio',
      ...(flowing ? share(row.fact_to_target) : MISSING)
    },
    {
      key: 'watercut',
      ...(live && row.role !== 'INJ' ? share(row.watercut) : MISSING)
    },
    {
      key: 'bhp',
      ...(live ? number(row.bhp, 1) : MISSING)
    },
    {
      key: 'cumulative',
      ...(row === undefined ? MISSING : number(row.cumulative_liquid, 0))
    },
    {
      key: 'npv',
      ...(npv === undefined ? MISSING : number(npv, 0))
    },
    {
      key: 'group',
      ...(group === undefined || group === null ? MISSING : measured(group))
    }
  ].map((fact) => ({
    key: fact.key,
    label: t(`chrono.readout.${fact.key}`),
    value: fact.text,
    measured: fact.measured
  }));

  const { flipX, flipY, nudgeX, nudgeY, room } = readoutPlacement(target, bounds, height);

  return (
    <div
      className="chronomap-readout"
      data-testid="chronomap-readout-anchor"
      style={{ left: `${target.x}px`, top: `${target.y}px` }}
    >
      <div
        ref={panel}
        className="chronomap-readout-panel"
        role="tooltip"
        data-closing={closing}
        data-testid="chronomap-readout"
        data-flip-x={flipX}
        data-flip-y={flipY}
        style={
          {
            '--readout-room': `${room}px`,
            '--readout-nudge-x': `${nudgeX}px`,
            '--readout-nudge-y': `${nudgeY}px`
          } as Record<string, string>
        }
      >
        <header className="chronomap-readout-head">
          <span className="chronomap-readout-well">
            {t('chrono.readout.well', { well: target.well })}
          </span>
          <span className="chronomap-readout-date">
            {step === undefined ? DASH : formatStepDate(lang, step.date)}
          </span>
        </header>

        <div className="chronomap-readout-state">
          <span
            className="chronomap-readout-mode"
            data-mode={row === undefined ? 'unknown' : modeOf(row)}
          >
            {row === undefined ? t('chrono.value.unknown') : t(`chrono.mode.${modeOf(row)}`)}
          </span>
          {step?.terminal === true && (
            <span className="chronomap-readout-terminal">{t('chrono.terminalNote')}</span>
          )}
        </div>

        <p className="chronomap-readout-lead" data-metric={metric}>
          {t(`chrono.value.${metric}`, { value: readingText({ lang, t, metric, row, npv }) })}
        </p>

        <dl className="chronomap-readout-facts">
          {facts.map((fact) => (
            <div className="chronomap-readout-fact" key={fact.key}>
              <dt className="chronomap-readout-label">{fact.label}</dt>
              <dd
                className="chronomap-readout-value"
                data-fact={fact.key}
                data-measured={fact.measured}
                title={fact.measured ? undefined : t('chrono.value.unknown')}
              >
                {fact.value}
              </dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  );
};
