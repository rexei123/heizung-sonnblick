import { EmptyState } from "@/components/patterns/empty-state";

export default function ProfilePage() {
  return (
    <EmptyState
      title="Profile"
      description="Tag-, Nacht- und Wochenend-Heizprofile für Räume."
      plannedSprint="Sprint 9.15"
      icon="assignment_ind"
    />
  );
}
