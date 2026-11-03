## Der Boost-Wert steht in den Daten, nicht in einer fremden Grenze (2026-11-02)

**Migration additiv: ja.** `0037_boost_temperatur` — reine
Daten-Migration, kein Schema-Eingriff.

**Widerspruch des Betreibers**, und er hat recht.

### Was falsch war

Der erste Entwurf nahm `guest_override_max` derselben Kette, wenn
`rule_config.boost_temperature` leer war — mit der Begründung, das sei
„der höchste Wert, den die Rezeption ohnehin eingeben darf", und ohne
Rückfall wäre die Funktion am Tag des Einbaus tot (die Spalte ist nach
`0036` überall `NULL`).

**`guest_override_max` ist die Gast-Obergrenze.** Sie kann 25 sein,
während der festgelegte Boost-Wert **23** ist. Ein Rückfall darauf macht
aus einem Boost stillschweigend das Maximum — und zwar an der Stelle, an
der es niemandem auffällt, weil beides eine plausible Zahl ist.

**Der Fehler war nicht die Zahl, sondern die Vertauschung von zwei
Fragen.** „Was darf der Gast höchstens einstellen" und „worauf heizt ein
Boost" haben verschiedene Antworten, und dass die erste zufällig
verfügbar war, macht sie nicht zur zweiten. Dasselbe Muster wie §5.73
(Prozent statt Spannung): ein Wert, der in der Nähe liegt, ist kein Wert,
der dasselbe bedeutet.

### Was jetzt gilt

| | |
|---|---|
| **Quelle** | `rule_config.boost_temperature`, Kette Zimmer > Raumtyp > hausweit — **und nur das** |
| **Migration `0037`** | setzt die **hausweite** Zeile auf **23,0**, wenn sie leer ist |
| **steht trotzdem nichts da** | Boost wird abgewiesen: **„Boost-Temperatur nicht eingestellt"** |
| **Rückfall** | keiner |

**Nur ein `UPDATE`, kein `INSERT`.** Gibt es keine hausweite Zeile, legt
die Migration auch keine an: eine Zeile zu erfinden, um einen
Vorgabewert unterzubringen, wäre eine Entscheidung über die
Konfiguration des Hauses. Im Haus existiert sie (sie trägt heute
`t_night`); in einer frischen Datenbank nicht, und dort ist „nicht
eingestellt" die richtige Antwort.

**`WHERE boost_temperature IS NULL`** — ein gesetzter Wert wird nicht
überschrieben. `0036` ist seit heute in `develop`; jemand kann den Wert
von Hand gesetzt haben, und ihn zurück auf 23 zu ziehen wäre eine stille
Änderung an einer wirksamen Einstellung.

**Der `downgrade` setzt nichts zurück** und ist absichtlich leer. Er kann
nicht unterscheiden, ob die 23,0 von der Migration oder von einem
Menschen kommt — und ein Rückweg, der eine bewusst gesetzte Einstellung
löscht, ist schlimmer als keiner. `0036` entfernt die Spalte ohnehin
vollständig, wenn man so weit zurückgeht.

### Beim Bauen aufgefallen

**Der Typ am Bindparameter ist Pflicht.** Ohne ihn schickt asyncpg den
Wert als `character varying`, und Postgres weist das ab: „column is of
type numeric but expression is of type character varying". Ein Literal in
der SQL-Zeichenkette wäre die andere Lösung und die schlechtere — dann
stünde die Zahl zweimal da.

### Mutationsproben

| Mutation | gefallen |
|---|---|
| Rückfall auf `guest_override_max` wieder eingebaut | der neue API-Test (25 steht da, Boost wird trotzdem abgewiesen) |
| Migration überschreibt einen gesetzten Wert | der Migrations-Test |
| Migration setzt nichts | der Migrations-Test |

### Dazu: die Abnahme-Schrittliste

**RUNBOOK §10ax** — reine Oberflächen-Prüfung, kein SSH, rund 15 Minuten:
belegtes und freies Zimmer, die Endzeit am Knopf, zweimal boosten, die
vier Abweisungen, beide Rollen, das Protokoll. Mit dem, was **nicht**
geprüft wird, und warum.

**Der erste Schritt ist die Migration**, und das ist kein Formalismus:
steht die Datenbank auf `0036`, wird **jeder** Boost mit
„Boost-Temperatur nicht eingestellt" abgewiesen — dann ist nicht der
Boost kaputt, sondern `0037` nicht gelaufen. Ohne diesen Schritt sähe die
Abnahme wie ein Fehler in der Funktion aus.
