import { EmptyState } from "@/components/patterns/empty-state";

export default function ApiWebhooksPage() {
  return (
    <EmptyState
      title="API & Webhooks"
      description="API-Tokens, Webhook-Endpunkte und Integrationen."
      plannedSprint="Sprint 9.20"
      icon="api"
    />
  );
}
