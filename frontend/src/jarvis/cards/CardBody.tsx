import type { ConsoleAction } from '../actions/consoleAction';
import type { JarvisCard } from '../transport/events';
import { CompareCard } from './CompareCard';
import { ErrorCard } from './ErrorCard';
import { EventStripCard } from './EventStripCard';
import { FieldMapCard } from './FieldMapCard';
import { GlossaryCard } from './GlossaryCard';
import { GuideCard } from './GuideCard';
import { MetricCard } from './MetricCard';
import { PatternCard } from './PatternCard';
import { RuleCard } from './RuleCard';
import { SeriesCard } from './SeriesCard';
import { WellCard } from './WellCard';
import { WellListCard } from './WellListCard';

interface CardBodyProps {
  card: JarvisCard;
  onOpen: (action: ConsoleAction) => void;
}

export const CardBody = ({ card, onOpen }: CardBodyProps) => {
  if (card.type === 'metric') {
    return <MetricCard payload={card.payload} />;
  }
  if (card.type === 'well') {
    return <WellCard payload={card.payload} />;
  }
  if (card.type === 'well-list') {
    return <WellListCard payload={card.payload} />;
  }
  if (card.type === 'series') {
    return <SeriesCard payload={card.payload} />;
  }
  if (card.type === 'field-map') {
    return <FieldMapCard payload={card.payload} />;
  }
  if (card.type === 'rule') {
    return <RuleCard payload={card.payload} />;
  }
  if (card.type === 'compare') {
    return <CompareCard payload={card.payload} />;
  }
  if (card.type === 'event-strip') {
    return <EventStripCard payload={card.payload} />;
  }
  if (card.type === 'pattern') {
    return <PatternCard payload={card.payload} />;
  }
  if (card.type === 'glossary') {
    return <GlossaryCard payload={card.payload} onOpen={onOpen} />;
  }
  if (card.type === 'guide') {
    return <GuideCard payload={card.payload} onOpen={onOpen} />;
  }
  return <ErrorCard payload={card.payload} />;
};
