import { NextResponse } from 'next/server'

/**
 * Healthcheck-Endpoint fuer den Web-Container.
 *
 * Pfad: /healthz (K8s-Konvention).
 *
 * Warum nicht /api/health? Caddy routet `path /api/*` an die Backend-
 * FastAPI weiter - eine Frontend-Route unter /api/* ist von extern
 * nicht erreichbar. /healthz liegt ausserhalb des Caddy-API-Matchers
 * und geht damit korrekt an den Web-Container.
 *
 * Eigenschaften:
 *  - force-static: kein Request-Kontext, maximale Antwortgeschwindigkeit
 *  - keine DB- oder API-Abhaengigkeit
 *  - wird vom Docker-HEALTHCHECK alle 30s aufgerufen
 *  - extern erreichbar via https://<host>/healthz fuer Monitoring
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
