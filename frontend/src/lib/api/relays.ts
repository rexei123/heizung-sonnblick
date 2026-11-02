/**
 * API-Funktionen fuer Relais-Aktoren (Sprint 24b, Paket 6).
 *
 * Zod-Spiegel zu den Pydantic-Schemata in
 * ``backend/src/heizung/api/v1/relays.py`` (§5.63). Schlaegt die
 * Validierung fehl, wirft ``parse`` — TanStack Query rendert dann den
 * Fehler-Zustand, statt eine halbe Karte zu zeigen.
 *
 * **Alle Handlungen sind Admin-Wege, und die Pruefung sitzt im
 * Backend.** Die Oberflaeche blendet die Knoepfe fuer andere Rollen aus,
 * aber das ist Bequemlichkeit und kein Schutz — wer den Weg direkt
 * aufruft, bekommt 403. Mutationsprobe M12 prueft genau das.
 */

import { z } from "zod";

import { apiClient } from "./client";

/** Der Stand eines Relais. Messwerte sind ``null``, nicht ``0``, wenn
 * es keine Meldung gibt — eine 0 bei der Leistung waere eine Behauptung
 * ueber ein Geraet, von dem wir nichts gehoert haben. */
export const relaisStandSchema = z.object({
  device_id: z.number(),
  dev_eui: z.string(),
  label: z.string().nullable(),
  firmware_version: z.string().nullable(),
  last_seen_at: z.string().nullable(),

  commissioned_at: z.string().nullable(),
  power_return_verified: z.boolean(),
  overheating_recovery_verified: z.boolean(),
  protection_tripped_at: z.string().nullable(),
  protection_kind: z.string().nullable(),
  switch_cycles: z.number(),
  watchdog_strategy: z.string(),
  darf_schalten: z.boolean(),
  // Seit dem 01.11.2026 sendet ein Hintergrund-Auftrag, und der
  // Request kehrt sofort zurück. Ohne dieses Feld gäbe es keinen
  // Unterschied zwischen „noch nicht angestoßen" und „läuft gerade" —
  // und genau diese Lücke hat den Handgriff zweimal machen lassen.
  provisionierung_laeuft: z.boolean(),

  // Der unbestätigte Schaltbefehl. Bis zum 02.11.2026 hatte dieser
  // Zustand keinen Leser außer dem Orchestrator: ein Relais, das seit
  // Stunden nicht bestätigt, stand als Alarm im Log und sonst nirgends
  // (§5.76). Seit der Alarm den offenen Stand nicht mehr löscht, lebt er
  // außerdem beliebig lange.
  //
  // ``gemeldet`` kommt **aus dem Backend**: die Schwelle steht in den
  // Settings, und eine zweite Kenntnis davon hier wäre beim ersten
  // Nachjustieren falsch (§5.73).
  offener_befehl: z
    .object({
      ziel_ein: z.boolean(),
      seit: z.string(),
      versuche: z.number(),
      gemeldet: z.boolean(),
    })
    .nullable(),

  relay_on: z.boolean().nullable(),
  power_w: z.number().nullable(),
  energy_wh: z.number().nullable(),
  internal_temperature_raw: z.number().nullable(),
  gehaeusetemperatur_alarm: z.boolean(),
  reading_time: z.string().nullable(),
  change_reason: z.string().nullable(),
});

export type RelaisStand = z.infer<typeof relaisStandSchema>;

const provisionierungSchema = z.object({
  device_id: z.number(),
  // „geplant", nicht „gesendet": der Endpunkt kehrt zurück, bevor der
  // erste Downlink hinaus ist (01.11.2026).
  geplant: z.array(z.string()),
  laeuft: z.boolean(),
  hinweis: z.string(),
});

export type Provisionierung = z.infer<typeof provisionierungSchema>;

const inbetriebnahmeSchema = z.object({
  device_id: z.number(),
  commissioned_at: z.string().nullable(),
  power_return_verified: z.boolean(),
  overheating_recovery_verified: z.boolean(),
});

export type Inbetriebnahme = z.infer<typeof inbetriebnahmeSchema>;

const messrolleSchema = z.object({
  device_id: z.number(),
  measure_only: z.boolean(),
  kindersicherung_gesendet: z.boolean(),
  hinweis: z.string(),
});

export type Messrolle = z.infer<typeof messrolleSchema>;

export async function fetchRelaisStand(deviceId: number): Promise<RelaisStand> {
  const data = await apiClient.get<unknown>(
    `/api/v1/devices/${deviceId}/relay`,
  );
  return relaisStandSchema.parse(data);
}

export async function provisioniereRelais(
  deviceId: number,
): Promise<Provisionierung> {
  const data = await apiClient.post<unknown>(
    `/api/v1/devices/${deviceId}/relay/provision`,
    {},
  );
  return provisionierungSchema.parse(data);
}

export async function nimmRelaisInBetrieb(
  deviceId: number,
): Promise<Inbetriebnahme> {
  const data = await apiClient.post<unknown>(
    `/api/v1/devices/${deviceId}/relay/commission`,
    {},
  );
  return inbetriebnahmeSchema.parse(data);
}

export async function nimmRelaisAusserBetrieb(
  deviceId: number,
): Promise<Inbetriebnahme> {
  const data = await apiClient.delete<unknown>(
    `/api/v1/devices/${deviceId}/relay/commission`,
  );
  return inbetriebnahmeSchema.parse(data);
}

export async function hebeSchutzSperreAuf(deviceId: number): Promise<void> {
  await apiClient.post<unknown>(
    `/api/v1/devices/${deviceId}/relay/release-protection`,
    {},
  );
}

export async function setzeMessrolle(
  deviceId: number,
  measureOnly: boolean,
): Promise<Messrolle> {
  const data = await apiClient.patch<unknown>(
    `/api/v1/devices/${deviceId}/measure-only`,
    {
      measure_only: measureOnly,
    },
  );
  return messrolleSchema.parse(data);
}
