/**
 * Geräte-Historie (Sprint 24c).
 *
 * Zod-Spiegel zu ``DeviceAuditEintrag`` in
 * ``backend/src/heizung/api/v1/devices.py`` (§5.63).
 *
 * ``alt`` und ``neu`` sind die JSONB-Werte des Audits und bleiben
 * **ungeprüft** (`z.unknown()`): ihr Inhalt hängt an der Aktion, und ein
 * Schema je Aktion wäre eine zweite Liste neben dem Backend. Die Anzeige
 * liest sie mit einer Typprüfung zur Laufzeit und fällt sonst auf den
 * Aktionsnamen zurück.
 *
 * Der Pfad trägt ``/api/v1`` selbst — ``apiClient`` setzt kein Präfix.
 * Die erste Fassung der Relais-Datei hatte das übersehen, und die
 * Anfragen gingen gegen die Next-App (404).
 */

import { z } from "zod";

import { apiClient } from "./client";

const eintragSchema = z.object({
  ts: z.string(),
  action: z.string(),
  benutzer: z.string().nullable(),
  alt: z.unknown().nullable(),
  neu: z.unknown().nullable(),
});

export type DeviceAuditEintrag = z.infer<typeof eintragSchema>;

export async function fetchDeviceAudit(deviceId: number): Promise<DeviceAuditEintrag[]> {
  const data = await apiClient.get<unknown>(`/api/v1/devices/${deviceId}/audit`);
  return z.array(eintragSchema).parse(data);
}
