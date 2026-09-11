import { DASH } from '@/shared/lib/format';
import { useT } from '@/shared/i18n/I18nContext';
import { readPhysics } from '@/jarvis/cards/payloads';
import { EmptyPayload } from '@/jarvis/cards/EmptyPayload/EmptyPayload';
import './PhysicsCard.css';

export const PhysicsCard = ({ payload }: { payload: unknown }) => {
  const t = useT();
  const physics = readPhysics(payload);
  if (physics === null) {
    return <EmptyPayload />;
  }

  return (
    <div className="jarvis-physics">
      <p className="jarvis-physics-head" data-ok={physics.admissible === true ? 'true' : 'false'}>
        <span className="jarvis-physics-run">{physics.run_id}</span>
        <span>
          {t('jarvis-cards.physicsAdmissible')}:{' '}
          {physics.admissible === null
            ? DASH
            : physics.admissible
              ? t('jarvis-cards.yes')
              : t('jarvis-cards.no')}
        </span>
      </p>
      <p className="jarvis-physics-counts">
        {t('jarvis-cards.physicsBlocking')} {physics.blocking ?? 0} ·{' '}
        {t('jarvis-cards.physicsWarnings')} {physics.warnings ?? 0}
      </p>
      {physics.checks.length === 0 ? null : (
        <ul className="jarvis-physics-checks">
          {physics.checks.map((check, index) => (
            <li key={`${check.id}-${index}`} data-status={check.status}>
              <span className="jarvis-physics-check-id">{check.id}</span>
              {check.detail === null ? null : (
                <span className="jarvis-physics-check-detail">{check.detail}</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};
