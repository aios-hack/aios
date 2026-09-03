import { formatStepDate } from '../../ui/format';
import { useI18n } from '../../i18n/I18nContext';
import { readEventStrip } from './cardPayloads';
import { EmptyPayload } from './EmptyPayload';
import './EventStripCard.css';

const EVENT_KEYS: Record<string, string> = {
  COMMISSIONED: 'jarvis.eventCommissioned',
  ROLE_CHANGE: 'jarvis.eventRoleChange',
  SHUT: 'jarvis.eventShut'
};

export const eventPosition = (step: number, from: number, to: number): number => {
  const span = to - from;
  if (span <= 0) {
    return 0;
  }
  return Math.min(Math.max((step - from) / span, 0), 1);
};

export const EventStripCard = ({ payload }: { payload: unknown }) => {
  const { lang, t } = useI18n();
  const strip = readEventStrip(payload);
  if (strip === null) {
    return <EmptyPayload />;
  }
  const kinds = [...new Set(strip.events.map((event) => event.type))];

  return (
    <div className="jarvis-events">
      <p className="jarvis-events-count">
        <span>{t('jarvis.eventsCount')}</span>
        <span className="jarvis-events-total">{strip.events.length}</span>
      </p>
      <div className="jarvis-events-strip">
        {strip.events.map((event) => (
          <span
            key={`${event.step}:${event.well}:${event.type}`}
            className="jarvis-events-mark"
            data-type={event.type}
            style={{
              insetInlineStart: `${eventPosition(event.step, strip.from_step, strip.to_step) * 100}%`
            }}
            title={`${event.well} · ${formatStepDate(lang, event.date)}`}
          />
        ))}
      </div>
      <ul className="jarvis-events-legend">
        {kinds.map((kind) => (
          <li key={kind}>
            <span className="jarvis-events-swatch" data-type={kind} aria-hidden="true" />
            {EVENT_KEYS[kind] === undefined ? kind : t(EVENT_KEYS[kind])}
          </li>
        ))}
      </ul>
    </div>
  );
};
