import { EmptyState } from "@/components/patterns/empty-state";

export default function TemperaturverlaufPage() {
  return (
    <EmptyState
      title="Temperaturverlauf"
      description="Historische Temperaturentwicklung pro Raum und Gerät."
      plannedSprint="Sprint 9.19"
      icon="monitoring"
    />
  );
}
