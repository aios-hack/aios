import type { ConsoleAction } from '@/jarvis/actions/lib/consoleAction';
import type { JarvisCard } from '@/jarvis/transport/events';
import { CompareCard } from '@/jarvis/cards/CompareCard/CompareCard';
import { ConstraintsCard } from '@/jarvis/cards/ConstraintsCard/ConstraintsCard';
import { CouncilCard } from '@/jarvis/cards/CouncilCard/CouncilCard';
import { DocCard } from '@/jarvis/cards/DocCard/DocCard';
import { ErrorCard } from '@/jarvis/cards/ErrorCard/ErrorCard';
import { EventStripCard } from '@/jarvis/cards/EventStripCard/EventStripCard';
import { FieldMapCard } from '@/jarvis/cards/FieldMapCard/FieldMapCard';
import { GlossaryCard } from '@/jarvis/cards/GlossaryCard/GlossaryCard';
import { GuideCard } from '@/jarvis/cards/GuideCard/GuideCard';
import { MetricCard } from '@/jarvis/cards/MetricCard/MetricCard';
import { PatternCard } from '@/jarvis/cards/PatternCard/PatternCard';
import { PhysicsCard } from '@/jarvis/cards/PhysicsCard/PhysicsCard';
import { RunCard } from '@/jarvis/cards/RunCard/RunCard';
import { RunListCard } from '@/jarvis/cards/RunListCard/RunListCard';
import { StatusBoardCard } from '@/jarvis/cards/StatusBoardCard/StatusBoardCard';
import { SystemMapCard } from '@/jarvis/cards/SystemMapCard/SystemMapCard';
import { RuleCard } from '@/jarvis/cards/RuleCard/RuleCard';
import { SeriesCard } from '@/jarvis/cards/SeriesCard/SeriesCard';
import { WellCard } from '@/jarvis/cards/WellCard/WellCard';
import { WellListCard } from '@/jarvis/cards/WellListCard/WellListCard';

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
    return <FieldMapCard payload={card.payload} scenario={card.action?.scenario ?? null} />;
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
  if (card.type === 'doc') {
    return <DocCard payload={card.payload} />;
  }
  if (card.type === 'system-map') {
    return <SystemMapCard payload={card.payload} onOpen={onOpen} />;
  }
  if (card.type === 'status-board') {
    return <StatusBoardCard payload={card.payload} />;
  }
  if (card.type === 'run-list') {
    return <RunListCard payload={card.payload} />;
  }
  if (card.type === 'run') {
    return <RunCard payload={card.payload} />;
  }
  if (card.type === 'constraints') {
    return <ConstraintsCard payload={card.payload} />;
  }
  if (card.type === 'council') {
    return <CouncilCard payload={card.payload} />;
  }
  if (card.type === 'physics') {
    return <PhysicsCard payload={card.payload} />;
  }
  return <ErrorCard payload={card.payload} />;
};
