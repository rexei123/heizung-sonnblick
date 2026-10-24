/**
 * Kennzeichnung „Fühler" (Sprint 24c).
 *
 * Ein Gerät mit der Rolle „nur messen" sieht in jeder Liste aus wie ein
 * normales Thermostat — es hat dieselben Felder, dieselbe Bezeichnung,
 * denselben Hardware-Status. Nur tut es etwas anderes: es misst und
 * stellt nicht. Ohne Kennzeichnung sucht jemand eine Ventilstellung, die
 * es nie geben wird, und liest ein fehlendes Vorheizen als Fehler.
 *
 * **Eine Komponente für beide Stellen** (Zonenansicht und Geräteliste).
 * Zwei Fassungen desselben Hinweises wären beim ersten Umformulieren
 * zwei verschiedene Hinweise (§5.53).
 *
 * **Material Symbol, kein Emoji** — Vorgabe des Briefs, und sie hat
 * einen Grund: ein Emoji rendert je Betriebssystem anders und trägt
 * keine Barrierefreiheits-Bedeutung. Das Symbol heißt `sensors`.
 *
 * `title` **und** `aria-label`: der Tooltip erklärt es dem Sehenden, das
 * Label dem Screen-Reader. Ein Symbol ohne beides wäre semantisch blind
 * (§5.57).
 */

export function FuehlerBadge({ className }: { className?: string }) {
  return (
    <span
      data-testid="fuehler-badge"
      className={`inline-flex items-center gap-1 rounded-full bg-surface-alt px-2 py-0.5 text-text-secondary text-xs ${className ?? ""}`}
      title="Nur messen: Dieses Gerät erhält keine Sollwerte und stellt nichts."
      aria-label="Fühler, nur messen"
    >
      <span className="material-symbols-outlined" aria-hidden style={{ fontSize: 14 }}>
        sensors
      </span>
      Fühler
    </span>
  );
}
