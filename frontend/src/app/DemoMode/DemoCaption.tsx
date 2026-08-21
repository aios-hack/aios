import { useI18n } from '../../i18n/I18nContext';
import { formatNumber, formatStepDate } from '../../ui/format';
import type { DemoScript, ResolvedFrame } from './frames';
import './DemoMode.css';

interface DemoCaptionProps {
  frame: ResolvedFrame;
  script: DemoScript;
}

const elapsedMs = (script: DemoScript, frame: ResolvedFrame): number =>
  script.frames
    .filter((entry) => entry.index <= frame.index)
    .reduce((sum, entry) => sum + entry.holdMs, 0);

export const DemoCaption = ({ frame, script }: DemoCaptionProps) => {
  const { t, lang } = useI18n();
  const event = frame.event;
  const text =
    event === null
      ? t('demo.caption.OVERVIEW')
      : t(`demo.caption.${event.type}`, {
          well: event.well ?? '',
          rule: event.rule ?? ''
        });
  const done = elapsedMs(script, frame);

  return (
    <figure className="demo-figure" data-testid="demo-figure">
      <span className="demo-progress" aria-hidden="true">
        <span
          className="demo-progress-fill"
          data-testid="demo-progress"
          style={{ width: `${(done / script.totalMs) * 100}%` }}
        />
      </span>
      <figcaption className="demo-caption" data-testid="demo-caption">
        <span className="demo-caption-position">
          {t('demo.position', {
            frame: script.frames.indexOf(frame) + 1,
            total: script.frames.length
          })}
        </span>
        <span className="demo-caption-date">{formatStepDate(lang, frame.date)}</span>
        <span className="demo-caption-text" data-event={event?.type ?? 'OVERVIEW'}>
          {text}
        </span>
        <span className="demo-caption-npv">
          <span className="demo-caption-npv-label">{t('demo.npvLabel')}</span>
          <span className="demo-caption-npv-value" data-testid="demo-npv">
            {formatNumber(lang, frame.npvCumulative)}
          </span>
        </span>
      </figcaption>
    </figure>
  );
};
