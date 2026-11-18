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
import { dezimalFeld } from "./zahlen";

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
  // Ab 25 Minuten Stille gilt der gemeldete Zustand als unbekannt. Die
  // Schwelle entscheidet das Backend (relay_meldeintervall_s x 2,5) --
  // hier noch einmal zu rechnen waere eine zweite Wahrheit.
  zustand_veraltet: z.boolean(),
  // Empfangsdaten des jüngsten Uplinks (Migration 0041). `null` heißt
  // "diese Meldung sagt nichts darüber", nicht "kein Empfang".
  rssi_dbm: z.number().nullable(),
  // **Der Fehler vom 18.11.2026.** Hier stand ``z.number().nullable()``,
  // und das Backend schickte ``"-8.0"`` — ein ``Decimal`` ohne
  // ``field_serializer``. ``parse`` warf, und die Karte zeigte „Der Stand
  // des Relais ist nicht abrufbar.": kein Schaltzustand, kein Sperrgrund,
  // keiner der vier Handgriffe, wegen der Zahl am Fuß der Karte.
  //
  // Sichtbar wurde es erst, als die Relais ihren ersten echten SNR
  // meldeten — bis dahin war das Feld ``null``, und ``null`` passt in
  // jeden Spiegel (§5.93). Das Backend serialisiert jetzt als Zahl;
  // ``dezimalFeld`` nimmt weiterhin beides und ist die zweite Linie.
  snr_db: dezimalFeld,
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

/**
 * Die zwei Wächter-Strategien, als Wort und nicht als Zahl.
 *
 * Die Liste spiegelt das `Literal` im Backend
 * (`api/v1/relays.StrategieEingabe`). Ein dritter Wert hier wäre eine
 * Behauptung über einen Endpunkt, der ihn ablehnt.
 */
export const WAECHTER_STRATEGIEN = ["expire_and_resend", "refresh"] as const;
export type WaechterStrategie = (typeof WAECHTER_STRATEGIEN)[number];

const strategieSchema = z.object({
  device_id: z.number(),
  strategie: z.enum(WAECHTER_STRATEGIEN),
  timer_sekunden: z.number(),
  hinweis: z.string(),
});

export type StrategieErgebnis = z.infer<typeof strategieSchema>;

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

/**
 * Schaltet die Wächter-Strategie um. **Nur Admin**, und ohne Funkbefehl.
 *
 * Der Handgriff schreibt Audit und setzt `relais_ein_gesendet_at`
 * zurück; gesendet wird erst beim nächsten regulären Lauf des
 * Orchestrators. Das ist der Grund, warum die Karte danach keinen
 * Funkverkehr meldet — sie hat keinen ausgelöst.
 */
export async function setzeWaechterStrategie(
  deviceId: number,
  strategie: WaechterStrategie,
): Promise<StrategieErgebnis> {
  const data = await apiClient.patch<unknown>(
    `/api/v1/devices/${deviceId}/relay/watchdog-strategy`,
    { strategie },
  );
  return strategieSchema.parse(data);
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
