# Sprint 22 — Rollen: kein Knopf, der mit 403 endet

**Stand:** 2026-10-14 · **Befund des Hoteliers**, hier am Code belegt ·
**direkt gebaut** (Freigabe 14.10., drei PRs) · Autonomie-Stufe 2

---

## 0. Die zwei Befunde, und was sie nicht waren

Sichtprobe am 14.10.2026, angemeldet als **`mitarbeiter`**, nichts
ausprobiert:

- **A:** Unter „Szenarien" war der **Sommermodus**-Schalter sichtbar und
  bedienbar — und der Bestätigungsdialog sagt, dass **alle Räume** auf
  Frostschutz gehen.
- **B:** Zimmer → Heizzonen zeigte **„Zone löschen"** und das Formular
  **„Neue Heizzone / Hinzufügen"**.

**Beides war serverseitig zu.** Nachgesehen, nicht vermutet:

| Endpoint | Gate | Fundstelle |
|---|---|---|
| `POST /scenarios/{code}/activate` · `/deactivate` | `require_admin` | `scenarios.py:181`, `:213` |
| `POST /rooms/{id}/heating-zones` | `require_admin` | `heating_zones.py:157` |
| `PATCH …/heating-zones/{id}` | `require_admin` | `heating_zones.py:200` |
| `DELETE …/heating-zones/{id}` | `require_admin` | `heating_zones.py:247` |

`ScenarioAssignment` wird **nirgends sonst** in `api/` geschrieben, und
`global_config.summer_mode_active` existiert seit AE-49 nicht mehr — es gab
also keinen zweiten Weg zum Sommermodus.

**Kein S1-Fall, und das ist der Grund für diesen Sprint, nicht gegen ihn.**
Es waren zehn Sackgassen: Handlungen, die mit 403 enden. Bei „hotelweit
Frostschutz" ist das besonders unangenehm, weil man bis zum Klick glaubt,
man habe gerade das Haus umgestellt. Derselbe Fehlertyp wie „Zimmer
löschen" in Sprint 21 A2 — das Muster war da, nur nirgends sonst
angewendet.

Dass der Hotelier **nichts ausprobiert hat**, ist der Grund, dass hier über
Gates geredet wird und nicht über einen Vorfall.

---

## 1. Die Durchsicht: 33 schreibende Endpunkte, 18 Seiten

**Serverseitig ist nichts offen.** 23 × `require_admin`, 6 ×
`require_mitarbeiter` (Belegungen anlegen/ändern/stornieren, Override
setzen/aufheben, Sperre umschalten), 1 × `require_real_user`
(Passwort ändern), 2 bewusst offen (`/auth/login`, `/auth/logout`) und
1 Token-geschützt (`POST /integrations/occupancy-import` über
`X-Webhook-Token`, `integrations.py:58`).

**In der Oberfläche fehlte das Gating an zehn Stellen:**

| Seite | Knopf / Feld | Gate | sah Mitarbeiter | Task |
|---|---|---|---|---|
| Szenarien | Sommermodus ein/aus | admin | **ja** | T2 |
| Zimmer → Heizzonen | „Zone löschen" | admin | **ja** | T3 |
| Zimmer → Heizzonen | „Neue Heizzone" | admin | **ja** | T3 |
| Raumtypen | Anlegen / Ändern / Löschen | admin | **ja** | T4 |
| Temperaturen & Zeiten | Speichern | admin | **ja** | T4 |
| Einstellungen → Hotel | Speichern | admin | **ja** | T4 |
| API & Webhooks | Speichern (Uhrzeit) | admin | **ja** | T4 |
| Zimmerübersicht | „Zimmer anlegen" | admin | **ja** | T5 |
| Thermostate | Bezeichnung inline | admin | **ja** | T5 |
| Thermostate → Pairing | Gerät anlegen, Zone zuordnen | admin | **ja** | T5 |

Richtig war es schon an diesen Stellen: Zimmer-Stammdaten, „Zimmer
löschen", die Geräte-Handgriffe im Zimmer (alle Sprint 21 A2), der
Zonenname (Sprint 14e), die Benutzer-Seite (Redirect) — und die
Mitarbeiter-Handlungen Belegungen und Übersteuerung, die sichtbar
**bleiben**.

**`zone-card.tsx` ist der Beleg, dass es knapp danebengehen kann:** dort
gated `isAdmin` **nur** den Namens-Edit (Zeile 87), während „Zone löschen"
achtzig Zeilen weiter unten offen stand. Ein halbes Gating sieht wie ein
ganzes aus.

---

## 2. Tasks

| | Inhalt | PR | Aufwand |
|---|---|---|---|
| **T1** | `darfKonfigurationAendern` in `lib/auth/rechte.ts`; `darfStammdatenAendern` auf Raumtypen und Heizzonen erweitert; die verstreuten `user?.role === "admin"` darauf umgestellt | 1 | 0,5 h |
| **T2** | Szenarien: Zustand lesbar, Schalter nur für Admin | 1 | 0,5 h |
| **T3** | Heizzonen: Löschen und Anlegen gated, `zone-card` vollständig statt halb | 1 | 0,5 h |
| **T4** | Raumtypen, Temperaturen & Zeiten, Hotel, API & Webhooks: lesbar, Speichern gesperrt mit Grund | 2 | 1,5 h |
| **T5** | Zimmerübersicht, Thermostate-Label, „Gerät hinzufügen", Pairing-Seite | 2 | 1 h |
| **T6** | Seitenleiste: „Benutzer" für Mitarbeiter ausblenden, Konfig-Seiten **und** „API & Webhooks" lesbar sichtbar | 3 | 0,5 h |
| **T7** | Status-Feld: Beschriftung, Hinweis, Bestätigung — plus Sichtbarkeit angehaltener Zimmer (§3) | 3 | 1 h |
| **T8** | e2e: beide Rollen über alle zehn Stellen | 1-3 | 1 h |
| **T9** | Doku: Gate-Inventar ins RUNBOOK mit Datum und Commit, STATUS | 3 | 0,75 h |

**Entscheidungen des Hoteliers vom 14.10.:** drei PRs (T1-T3 / T4-T5 /
T6-T9), je mit §0.3-Frage; in der Seitenleiste **nur „Benutzer"**
ausblenden; Konfig-Seiten sichtbar und lesbar; Gate-Inventar ins RUNBOOK.

**Zu „API & Webhooks": die Bedingung war „nichts Vertrauliches belegen",
und das ist belegt.** Das Formular hat genau ein Feld (die
Erwartungs-Uhrzeit des Imports, §5.79), die Liste zeigt Zeitpunkte, die
mailparser-Request-ID und **Zählwerte** — keine Gästenamen, kein Token,
keine URL; der Webhook-Token lebt nur in der `.env`. Die Seite bleibt
deshalb sichtbar und lesbar (Entscheidung vom 14.10., nach dem Beleg): der
Import-Status ist eine Mitarbeiter-Frage („ist die Liste von heute da?").

**Die Grenze des Belegs, benannt:** `alert_email` reist im
`global-config`-Paket mit, **angezeigt** wird sie dort nicht. Ausblenden
hätte daran nichts geändert — dieselbe Antwort holt die Hotel-Seite, die
ohnehin sichtbar bleibt.

---

## 3. T7 im Detail: ein angehaltenes Zimmer darf nicht lautlos sein

`sync_room_status` überschreibt den Status **nicht**, wenn er `CLEANING`
oder `BLOCKED` ist — die gelten als manuell gesetzt
(`occupancy_service.py:242`). Das Feld „Status (manuell)" in den
Stammdaten ist damit **halb**-automatisch:

| Hand gesetzt auf | Folge |
|---|---|
| belegt / frei / reserviert | **in 60 s überschrieben** — der Handgriff ist folgenlos |
| **Reinigung / Gesperrt** | **bleibt** und hält den Belegungs-Abgleich für dieses Zimmer an |

Das Risiko ist also nicht, dass Personal glaubt es müsse pflegen, sondern
dass ein „Gesperrt" ein Zimmer aus der Automatik nimmt, **ohne dass das
irgendwo steht**.

T7 liefert deshalb drei Dinge: die Beschriftung **„Status (automatisch aus
Belegungen)"** mit Hinweis, eine **Bestätigung** beim Setzen von Reinigung
oder Gesperrt (wie im Gefahrenbereich), und die **Sichtbarkeit**: ein
Etikett in der Zimmerübersicht und in der Zimmer-Kopfzeile der Satz
**„Automatik angehalten (Status: Gesperrt)"**.

---

## 4. Akzeptanzkriterien

| | Kriterium | Wie geprüft |
|---|---|---|
| **AK 1** | Als `mitarbeiter`: an keiner der zehn Stellen ein Schreib-Steuerelement | e2e, beide Rollen |
| **AK 2** | Als `mitarbeiter`: Szenario-**Zustand** und Konfigurations-**Werte** bleiben lesbar | e2e + Sichtprobe |
| **AK 3** | Als `admin`: alles unverändert vorhanden | e2e (jeder Test fährt beide Rollen) |
| **AK 4** | Seitenleiste: „Benutzer" fehlt für `mitarbeiter`, „API & Webhooks" ist da und lesbar | e2e |
| **AK 5** | Ein Zimmer auf „Gesperrt" trägt in Liste und Kopfzeile den Hinweis | Sichtprobe |
| **AK 6** | Gate-Inventar im RUNBOOK, mit Datum und Commit | Durchsicht |

**Jeder e2e-Test fährt beide Rollen.** Ein Test, der nur „Mitarbeiter sieht
nichts" prüft, wäre auch grün, wenn der Knopf für **niemanden** mehr
erscheint.

---

## 5. Risiken

**G1 — Verstecken ist Bedienung, kein Zugangsschutz** (§5.30). Alle 33
Schreibpfade bleiben serverseitig geprüft; dieser Sprint ändert daran
nichts und darf nicht so gelesen werden.

**G2 — Ein Bestandstest, der keine Rolle mockt, verliert seinen Knopf.**
In A2 war das `devices-pairing.spec.ts`, in T2 `szenarien.spec.ts`: ohne
`/auth/me` bleibt `user` `null`, und `null` darf nichts. Solche Tests sind
nicht gegen die Rolle geprüft, sondern gegen sie **blind** — sie bekommen
einen Admin-Mock, keinen Workaround.

**G3 — Das Gate-Inventar altert** (§5.79). Es trägt deshalb Datum und
Commit, und die Regel dazu: wer einen Endpunkt anlegt, trägt ihn ein.

**Kein S1-S6-Fall.** Keine Migration, kein Steuerpfad, keine Engine.
