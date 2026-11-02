## Drei Anzeigen, die etwas anderes sagten als die Daten (2026-11-02)

**Keine Migration.** Drei Befunde des Betreibers vom 01.11.2026, alle
derselben Art: die Oberfläche beantwortet eine Frage, die so nicht
gestellt war.

### 1. „Was davon gilt" rechnete für die Bad-Vorlage mit der falschen Kette

**Befund:** „Raumtypen → Bad → Was davon gilt zeigt hausweit 21/15/19,
laut `_bad_zielwert` gilt die Bad-Vorlage 22/18/22."

Die Vorschau rechnete mit der Kette für ein **Zimmer dieses Typs** — und
so ein Zimmer gibt es nicht, der Raumtyp ist **0 Zimmern** zugeordnet.
Gewirkt haben seine Spalten die ganze Zeit über `rules.engine._bad_zielwert`,
und dort treten sie als eigene ROOM_TYPE-Zeile auf.

Die Anzeige rechnet jetzt mit **derselben** Kette und nennt die Quelle
**„Bad-Vorlage"** — eine eigene Marke, weil der Weg ein anderer ist als
bei „Raumtyp": die Werte gelten für die **Bad-Zonen aller Zimmer**, nicht
für Zimmer dieses Typs.

**Die Gegenprobe steht als Test daneben:** ohne Vorlage gewinnt die
hausweite Zeile weiter. Ohne sie wäre nicht zu unterscheiden, ob die
Vorschau die Vorlage erkennt oder jetzt **jedem** Raumtyp seine Spalte
zuspricht — und das wäre eine Anzeige, die überall das Falsche behauptet
statt an einer Stelle.

### 2. Ein Fühler stand auf „Nicht montiert" in Rot

**Befund:** „056 (`measure_only`) ‚Nicht montiert' in Rot – für Fühler
neutral anzeigen."

Ein Fühler misst die Raumluft. Ob er auf einem Ventil sitzt, ist für
seine Aufgabe ohne Belang; Rot behauptet einen Mangel, wo keiner ist. Die
Pille heißt dort jetzt **„Fühler"**, grau, mit der Unterzeile „misst nur
— Montage ohne Belang".

### 3. Ein Relais stand auf „Keine Daten (30 Min)", obwohl es sendet

**Befund:** „109 ‚Keine Daten (30 Min)' obwohl Relais sendet –
Health-Badge liest nur `sensor_reading`, nicht `relay_reading`."

Richtig — und der tiefere Grund ist, dass die Frage das Gerät nicht
trifft: **ein Relais hat keine Halterung.** Die Pille heißt dort jetzt
**„Relais"** mit „keine Halterung — die Montage wird nicht gemeldet",
und die Abfrage **bleibt aus**: ein Weg, dessen Antwort man ohnehin
verwirft, ist eine Anfrage, die niemand braucht.

**Nicht gebaut: `relay_reading` in den Montage-Endpunkt.** Das hätte die
Zahl gefüllt und die Frage nicht beantwortet. Wer wissen will, ob ein
Relais lebt, braucht einen **Online**-Indikator (`device.last_seen_at`) —
eigener Badge, eigener Sprint, so wie es im Kopf der Komponente seit
Sprint 17 steht.

### Die Rolle ist ein Pflicht-Prop

`HardwareStatusBadge` bekommt `rolle` ohne Vorgabewert — aus demselben
Grund wie `isPool`: ob „nicht montiert" ein Mangel ist, hängt daran, und
ein Default würde die Unterscheidung genau dort verschlucken, wo sie
gebraucht wird. Vier Aufrufstellen leiten sie aus `kind` und
`measure_only` ab.

### Mutationsproben

| Mutation | gefallen |
|---|---|
| Bad-Zweig in der Vorschau entfernt | der Bad-Test |
| Fühler-Zustand entfernt | Playwright |
| Relais fragt die Montage doch ab | Playwright — **erst im zweiten Versuch** |

**Die dritte Probe hat zuerst überlebt, und das war ein Fehler im Test.**
Die Zähl-Route stand **vor** `mockDetailPage` registriert, und Playwright
nimmt die zuletzt registrierte Route zuerst — sie war verdeckt, der
Zähler blieb immer 0. Eine Zusicherung, die nichts prüft (§5.55).
Umgestellt, danach fällt die Probe.
