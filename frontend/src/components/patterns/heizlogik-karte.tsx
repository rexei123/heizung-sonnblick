/**
 * Die Karte der Heizlogik (Paket 1).
 *
 * Eingänge → Schichten → Verteilung auf die Zonen → Versandfilter →
 * Gerät → Rückmeldung. Eine Zeichnung und keine Aufzählung, weil die
 * Frage, die sie beantwortet, eine Reihenfolge ist: *wo* wird mein Wert
 * überschrieben, und *warum* kommt er manchmal nicht am Heizkörper an.
 *
 * **Inline-SVG mit Farb-Variablen**, damit hell und dunkel ohne zweite
 * Datei funktionieren und der Druck nicht grau auf grau wird.
 * `currentColor` für Linien, `--color-*` für Flächen.
 *
 * **Keine Zahlen in der Zeichnung.** Sollwerte und Zeiten stehen in der
 * lebenden Tabelle darunter (`{{werte}}`); eine Zahl in einem SVG ist
 * genau die Stelle, an der niemand sie nachzieht.
 */

const KASTEN = "fill-[var(--color-surface)] stroke-[var(--color-border-strong)]";
const SCHICHT = "fill-[var(--color-surface-alt)] stroke-[var(--color-border-strong)]";

interface Schicht {
  nr: string;
  name: string;
  was: string;
}

const SCHICHTEN: Schicht[] = [
  { nr: "0", name: "Sommer", was: "alles aus, nur Frostschutz" },
  { nr: "1", name: "Grundwert", was: "belegt / frei / Betrieb" },
  { nr: "2", name: "Zeit", was: "Vorheizen, Absenkung" },
  { nr: "3", name: "Übersteuerung", was: "Gast oder Rezeption" },
  { nr: "4", name: "Sicherheit", was: "Fenster, abgenommen" },
  { nr: "5", name: "Kappung", was: "Grenzen des Raumtyps" },
];

export function HeizlogikKarte() {
  const breite = 860;
  const höhe = 470;

  return (
    <figure className="mb-6" data-testid="heizlogik-karte">
      <svg
        viewBox={`0 0 ${breite} ${höhe}`}
        className="h-auto w-full"
        role="img"
        aria-label="Weg eines Sollwerts: Eingänge, sechs Schichten, Verteilung auf die Zonen, Versandfilter, Thermostat, Rückmeldung"
      >
        <defs>
          <marker
            id="pfeil"
            viewBox="0 0 10 10"
            refX="9"
            refY="5"
            markerWidth="6"
            markerHeight="6"
            orient="auto-start-reverse"
          >
            <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--color-border-strong)" />
          </marker>
        </defs>

        <g
          className="text-[11px]"
          fill="var(--color-text-secondary)"
          fontFamily="system-ui, sans-serif"
        >
          {/* --- Eingänge --- */}
          <text x="10" y="18" className="text-[10px]" fill="var(--color-text-tertiary)">
            Eingänge
          </text>
          {[
            ["Belegungsliste", "Anreise, Abreise"],
            ["Einstellungen", "Hausstandard, Raumtyp"],
            ["Gast am Rad", "Drehung am Thermostat"],
            ["Rezeption", "Wunschtemperatur"],
          ].map(([titel, unter], i) => (
            <g key={titel} transform={`translate(10, ${30 + i * 58})`}>
              <rect width="150" height="46" rx="4" className={KASTEN} strokeWidth="1" />
              <text x="10" y="19" fill="var(--color-text-primary)" className="text-[11px]">
                {titel}
              </text>
              <text x="10" y="34" className="text-[10px]" fill="var(--color-text-tertiary)">
                {unter}
              </text>
              <line
                x1="150"
                y1="23"
                x2="205"
                y2={i === 0 ? 120 : i === 1 ? 70 : i === 2 ? 20 : -30}
                stroke="var(--color-border-strong)"
                strokeWidth="1"
                markerEnd="url(#pfeil)"
              />
            </g>
          ))}

          {/* --- Schichten --- */}
          <text x="215" y="18" className="text-[10px]" fill="var(--color-text-tertiary)">
            Schichten — in dieser Reihenfolge, jede darf überschreiben
          </text>
          {SCHICHTEN.map((s, i) => (
            <g key={s.nr} transform={`translate(215, ${30 + i * 48})`}>
              <rect width="250" height="40" rx="4" className={SCHICHT} strokeWidth="1" />
              <circle cx="20" cy="20" r="11" fill="var(--color-primary)" opacity="0.15" />
              <text
                x="20"
                y="24"
                textAnchor="middle"
                fill="var(--color-primary)"
                className="text-[11px]"
                fontWeight="600"
              >
                {s.nr}
              </text>
              <text x="40" y="17" fill="var(--color-text-primary)" className="text-[11px]">
                {s.name}
              </text>
              <text x="40" y="31" className="text-[10px]" fill="var(--color-text-tertiary)">
                {s.was}
              </text>
              {i < SCHICHTEN.length - 1 ? (
                <line
                  x1="125"
                  y1="40"
                  x2="125"
                  y2="48"
                  stroke="var(--color-border-strong)"
                  strokeWidth="1"
                  markerEnd="url(#pfeil)"
                />
              ) : null}
            </g>
          ))}

          {/* --- Verteilung auf die Zonen --- */}
          <line
            x1="465"
            y1="260"
            x2="520"
            y2="260"
            stroke="var(--color-border-strong)"
            strokeWidth="1"
            markerEnd="url(#pfeil)"
          />
          <g transform="translate(520, 180)">
            <rect width="150" height="160" rx="4" className={KASTEN} strokeWidth="1" />
            <text x="10" y="20" fill="var(--color-text-primary)" className="text-[11px]">
              Ein Wert je Zimmer
            </text>
            <text x="10" y="36" className="text-[10px]" fill="var(--color-text-tertiary)">
              Bad-Zonen rechnen noch
            </text>
            <text x="10" y="48" className="text-[10px]" fill="var(--color-text-tertiary)">
              einmal mit der Vorlage
            </text>
            {["Schlafzimmer", "Bad", "weitere Zone"].map((z, i) => (
              <g key={z} transform={`translate(10, ${66 + i * 30})`}>
                <rect width="130" height="24" rx="3" className={SCHICHT} strokeWidth="1" />
                <text x="8" y="16" className="text-[10px]" fill="var(--color-text-secondary)">
                  {z}
                </text>
              </g>
            ))}
          </g>

          {/* --- Versandfilter --- */}
          <line
            x1="670"
            y1="260"
            x2="700"
            y2="260"
            stroke="var(--color-border-strong)"
            strokeWidth="1"
            markerEnd="url(#pfeil)"
          />
          <g transform="translate(700, 150)">
            <rect
              width="150"
              height="130"
              rx="4"
              fill="var(--color-warning-soft)"
              stroke="var(--color-warning)"
              strokeWidth="1"
            />
            <text x="10" y="20" fill="var(--color-text-primary)" className="text-[11px]">
              Wird gesendet?
            </text>
            {[
              "Änderung ≥ 0,5 °C?",
              "oder 6 h vorbei?",
              "Gerät nur messen? → nein",
              "Relais? → eigener Weg",
            ].map((t, i) => (
              <text
                key={t}
                x="10"
                y={40 + i * 16}
                className="text-[10px]"
                fill="var(--color-text-secondary)"
              >
                {t}
              </text>
            ))}
            <text x="10" y="118" className="text-[10px]" fill="var(--color-text-tertiary)">
              sonst: nichts tun
            </text>
          </g>

          {/* --- Gerät --- */}
          <line
            x1="775"
            y1="280"
            x2="775"
            y2="320"
            stroke="var(--color-border-strong)"
            strokeWidth="1"
            markerEnd="url(#pfeil)"
          />
          <g transform="translate(700, 320)">
            <rect width="150" height="54" rx="4" className={KASTEN} strokeWidth="1" />
            <text x="10" y="20" fill="var(--color-text-primary)" className="text-[11px]">
              Thermostat
            </text>
            <text x="10" y="36" className="text-[10px]" fill="var(--color-text-tertiary)">
              stellt das Ventil
            </text>
            <text x="10" y="48" className="text-[10px]" fill="var(--color-text-tertiary)">
              Funk: bis 6 h Verzug
            </text>
          </g>

          {/* --- Rückmeldung --- */}
          <path
            d="M 700 374 L 480 420 L 180 420 L 180 400"
            fill="none"
            stroke="var(--color-border-strong)"
            strokeWidth="1"
            strokeDasharray="4 3"
            markerEnd="url(#pfeil)"
          />
          <text x="300" y="436" className="text-[10px]" fill="var(--color-text-tertiary)">
            Rückmeldung: Ist-Temperatur, Ventilstellung, Batterie, gemeldeter Sollwert
          </text>
          <text x="300" y="450" className="text-[10px]" fill="var(--color-text-tertiary)">
            — daraus kommen Verlauf, Melder und der Abgleich alle 15 Minuten
          </text>
        </g>
      </svg>
      <figcaption className="text-text-tertiary mt-2 text-xs">
        Der Weg eines Sollwerts. Von links nach rechts: was hineinkommt, wer
        es überschreiben darf, wie es auf die Zonen verteilt wird, warum
        nicht jede Änderung gesendet wird — und was zurückkommt.
      </figcaption>
    </figure>
  );
}
