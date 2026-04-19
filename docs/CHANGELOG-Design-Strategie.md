# Changelog — Design-Strategie

## v2.0.1 — 2026-04-19

**Patch — nur Konsistenzfehler behoben, keine Designänderungen.**

- Kapitel 10.3: `lucide-react` aus der Liste der verbindlichen NPM-Basis-Dependencies entfernt.

### Begründung

Die Original-Fassung v2.0 war in sich widersprüchlich:

- Kapitel 7 ("Icon-System"), 12.2 ("Do's & Don'ts") und 15 ("Kurz-Referenz") legen Material Symbols Outlined als **einziges** Icon-Set fest.
- Kapitel 10.3 listete `lucide-react` als verbindliche Abhängigkeit.

Der Widerspruch wurde in `ARCHITEKTUR-ENTSCHEIDUNGEN.md` als **AE-01** dokumentiert und hier aufgelöst: Material Symbols gewinnt, `lucide-react` wird aus dem Dependency-Set gestrichen.

### Technische Auswirkung

Keine. Das Frontend-Grundgerüst (Sprint 1) hat `lucide-react` nie in der `package.json` geführt. Material Symbols wird als CSS-Schrift via Google Fonts eingebunden (siehe `frontend/src/app/globals.css`).
