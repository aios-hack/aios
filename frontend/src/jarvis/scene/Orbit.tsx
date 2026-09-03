import { useState, type CSSProperties } from 'react';
import { useT } from '../../i18n/I18nContext';
import type { ConsoleAction } from '../actions/consoleAction';
import { Card } from '../cards/Card';
import { CardBody } from '../cards/CardBody';
import type { SceneCard } from '../scenes';
import { orbitSeats } from './orbitLayout';
import './Orbit.css';

interface OrbitProps {
  cards: readonly SceneCard[];
  onOpen: (action: ConsoleAction) => void;
}

const STAGGER_MS = 80;
const RADIUS = 1;

export const Orbit = ({ cards, onOpen }: OrbitProps) => {
  const t = useT();
  const [expanded, setExpanded] = useState<string | null>(null);
  const seats = orbitSeats(cards.length, RADIUS, STAGGER_MS);

  return (
    <div className="jarvis-orbit" aria-label={t('jarvis.orbitLabel')} role="group">
      {cards.map((entry, index) => {
        const seat = seats[index];
        const open = expanded === entry.id;
        const style = {
          '--orbit-x': `${seat.x}`,
          '--orbit-y': `${seat.y}`,
          '--orbit-delay': `${seat.delayMs}ms`
        } as CSSProperties;
        return (
          <div
            className="jarvis-orbit-seat"
            key={entry.id}
            style={style}
            data-open={open ? 'true' : undefined}
          >
            <Card
              card={entry.card}
              expanded={open}
              onToggle={() => setExpanded(open ? null : entry.id)}
              onOpenInConsole={() => {
                if (entry.card.action !== undefined) {
                  onOpen(entry.card.action);
                }
              }}
            >
              <CardBody card={entry.card} onOpen={onOpen} />
            </Card>
          </div>
        );
      })}
    </div>
  );
};
