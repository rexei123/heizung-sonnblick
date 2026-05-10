# Frontend Verify-Skripte

One-shot DOM-/Render-Beweisskripte fuer UI-Komponenten, deren
Marker-Attribute oder Render-Pfade sich nicht sinnvoll als
Jest/Vitest-Test fixieren lassen. Laufen ausserhalb der Test-Suite,
nicht in CI.

## dom-marker-proof.tsx (Sprint 9.10 T4)

Beweis fuer den DOM-Marker des Window-Indicators (Lesson 9.8d:
sichtbares Marker-Attribut ``data-testid="window-open-indicator"``,
damit das Engine-Decision-Panel zuverlaessig auf Layer-4-State
prueft).

Rendert ``WindowOpenIndicator`` via ``react-dom/server`` und
prueft:

- Positiver Pfad: ``extractWindowOpenSince`` liefert einen
  Timestamp -> Marker erscheint im HTML.
- Negativer Pfad: kein Window-Open-State -> Marker fehlt.

```powershell
cd C:\Users\User\dev\heizung-sonnblick\frontend
.\node_modules\.bin\tsx scripts\dom-marker-proof.tsx
```
