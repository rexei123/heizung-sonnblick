import { NextResponse } from 'next/server'

/**
 * Healthcheck-Endpoint für den Web-Container.
 *
 * - Statisch gerendert (force-static): kein Request-Kontext nötig,
 *   maximale Antwortgeschwindigkeit.
 * - Keine DB- oder API-Abhängigkeit: prüft nur, dass der Next.js-
 *   Prozess lebendig und ansprechbar ist.
 * - Wird vom Docker-HEALTHCHECK im Dockerfile alle 30 s aufgerufen.
 */
export const dynamic = 'force-static'
export const revalidate = false

export async function GET() {
  return NextResponse.json({
    ok: true,
    service: 'web',
    ts: new Date().toISOString(),
  })
}
