# Betterspace-Inventar 2026-05-07

**Erstellt am:** 2026-05-07 durch Cowork (Browser-Agent)
**Zweck:** Visuelle Inventarisierung des Betterspace-Referenzsystems
als Eingabe für den Architektur-Refresh 2026-05-07.

## Was hier liegt

Fünf JSON-Dateien aus zwei Cowork-Durchgängen:

| Datei | Inhalt |
|---|---|
| `betterspace_admin_inventar_run1.json` | Erster Durchgang, 21 Screens, oberflächliche Inventarisierung |
| `betterspace_admin_inventar_run1_tiefenpass.json` | Tiefenpass auf 6 Schlüssel-Screens (Tooltips, Edge-Cases, Modale) |
| `betterspace_admin_inventar_run1_periphery.json` | Peripherie-Screens (9 weitere) — Settings-Hub, Hilfesektionen |
| `betterspace_admin_inventar_run2.json` | Zweiter Durchgang, 10 zusätzliche Screens, Lücken-Schließung |
| `betterspace_admin_inventar_diff.json` | Diff zwischen run1 und run2 — was beim ersten Durchgang fehlte |

**Insgesamt:** 46 Screens dokumentiert.

## Wofür das Material genutzt wurde

Hauptergebnis dieser Inventarisierung war die Bestätigung, dass
unsere bestehende Strategie architektonisch solide ist — plus drei
substantielle Korrekturen:

1. **AE-42 Frostschutz zweistufig** — Bad mit Handtuchwärmer braucht
   andere untere Grenze als Flur (Hard-Cap im Code + Raumtyp-Override)
2. **AE-43 Geräte-Lifecycle als eigene UI-Disziplin** — Pairing-Wizard,
   Inline-Edit, Sortierung nach Fehlerstatus
3. **Drei-Ebenen-Hierarchie braucht UI auf allen drei Ebenen** —
   bisher nur Global rudimentär implementiert

Vollständiger Kontext in `docs/ARCHITEKTUR-REFRESH-2026-05-07.md` §1-§3.

## Status

Diese Daten sind eine **Momentaufnahme zum 2026-05-07**. Sie werden
nicht aktualisiert. Wenn neue Inventarisierungen folgen, kommen sie
in einen neuen Ordner (`docs/research/<system>-<datum>/`).

## Nicht für

- Live-Bezug: das ist Forschungsmaterial, kein laufendes Asset
- Sprint-Plan-Arbeit: dafür gilt `docs/SPRINT-PLAN.md`
- Code-Vorlagen: wir bauen eigene Lösung, nicht Betterspace nach
