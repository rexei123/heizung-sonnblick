/**
 * Startseite des Admin-UI.
 *
 * Aktuell: Redirect auf /devices (Geraeteliste). Sobald Sprint 8 die
 * Heizungs-Steuer-Logik bringt, wird hier eine echte Uebersicht (KPIs
 * pro Zone, Anzahl aktiver Devices, letzte Anomalien) entstehen.
 */
import { redirect } from "next/navigation";

export default function Home(): never {
  redirect("/devices");
}
