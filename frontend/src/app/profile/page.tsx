import { EmptyState } from "@/components/patterns/empty-state";

/**
 * Die Seite bleibt leer — und sagt jetzt, wo der Tagesplan steht
 * (21.11.2026).
 *
 * Der Brief in #421 hat vorgeschlagen, den Tagesplan hierher zu legen:
 * diese Seite verspricht seit Monaten „Tag-, Nacht- und
 * Wochenend-Heizprofile", und das ist genau der Wunsch. Gebaut wurde er
 * auf Vorgabe des Betreibers **am Zimmer**, neben der Betriebszeit — die
 * Zeit gehört zum Ort, nicht zur Art (die Begründung steht in
 * `services/betriebszeit` und gilt für den Plan wörtlich weiter).
 *
 * Damit steht hier eine Seite, die etwas verspricht, was es inzwischen
 * gibt — nur woanders. Ein Versprechen ohne Weg ist derselbe Fehler wie
 * ein Schalter ohne Wirkung (§5.77), deshalb nennt die Beschreibung den
 * Weg. Die Seite selbst bleibt ein Platzhalter: für Wochentag- und
 * Saison-Profile, von denen #421 in der ersten Stufe abgeraten hat.
 */
export default function ProfilePage() {
  return (
    <EmptyState
      title="Profile"
      description={
        "Tag-, Nacht- und Wochenend-Heizprofile für Räume. Den Tagesplan eines " +
        "Allgemeinbereichs — mehrere Zeitfenster am Tag, je Fenster ein Sollwert — " +
        "stellen Sie am Zimmer selbst ein: Zimmer öffnen, Reiter „Stammdaten“, " +
        "Abschnitt „Tagesplan“."
      }
      icon="assignment_ind"
    />
  );
}
