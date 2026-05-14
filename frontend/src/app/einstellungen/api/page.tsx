import { EmptyState } from "@/components/patterns/empty-state";

export default function ApiWebhooksPage() {
  return (
    <EmptyState
      title="API & Webhooks"
      description="API-Tokens, Webhook-Endpunkte und Integrationen."
      icon="api"
    />
  );
}
