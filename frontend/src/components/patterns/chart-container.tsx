"use client";

/**
 * Die Hülle um jedes Diagramm (Sprint 21 A1).
 *
 * **Der Befund.** Der Hotelier hat in der Konsole
 * `The width(-1) and height(-1) of chart should be greater than 0`
 * gesehen. Gemessen im Playwright-Lauf: die Meldung kommt bei **jedem**
 * Diagramm-Mount, auf der Geräteseite wie im neuen Verlauf.
 *
 * **Was nicht geholfen hat.** Die naheliegende Abhilfe — eine Mindesthöhe
 * am umgebenden `div` — war längst da (`h-72`). Die zweite Vermutung,
 * `minWidth`/`minHeight` am `ResponsiveContainer`, hat die Meldung
 * ebenfalls nicht beseitigt: recharts zählt beide Werte in der Warnung
 * selbst auf, kennt sie also und warnt trotzdem. Es warnt, *bevor* es die
 * Mindestwerte anwendet — der erste Messdurchlauf liefert -1, weil die
 * Breite im Layout noch nicht steht.
 *
 * **Was hilft: selbst messen.** Diese Hülle beobachtet ihre eigene Breite
 * und gibt dem Diagramm Zahlen statt Prozente. `ResponsiveContainer`
 * entfällt damit ganz — er ist eine Bequemlichkeit um genau diese
 * Messung, und recharts' Diagramme nehmen `width`/`height` als Zahlen
 * direkt.
 *
 * Der Preis ist ein Bildaufbau ohne Diagramm (ein Frame, bis die Messung
 * da ist). Das ist sichtbar nicht schlechter als vorher: `ResponsiveContainer`
 * rendert in diesem Moment ebenfalls nichts Brauchbares — nur mit einer
 * Zeile in der Konsole dazu.
 *
 * Zwei Diagramme, eine Stelle: das Gerät-Diagramm (Sprint 7) und der
 * Zimmer-Verlauf (A1) teilen diese Hülle. Ein drittes Diagramm bekommt
 * den Fix damit umsonst — und die e2e-Tests prüfen die Konsole an beiden
 * Stellen, damit die Meldung nicht unbemerkt zurückkommt.
 */

import { cloneElement, useEffect, useRef, useState, type ReactElement } from "react";

/** Höhe in px. 288 = `h-72`, die Höhe des bestehenden Diagramms. */
export const CHART_HOEHE = 288;

interface Masse {
  width?: number;
  height?: number;
}

interface Props {
  /** Ein recharts-Diagramm; es bekommt `width`/`height` als Zahlen. */
  children: ReactElement<Masse>;
  hoehe?: number;
  testId?: string;
}

export function ChartContainer({ children, hoehe = CHART_HOEHE, testId }: Props) {
  const huelle = useRef<HTMLDivElement>(null);
  const [breite, setBreite] = useState(0);

  useEffect(() => {
    const el = huelle.current;
    if (!el) return;
    const messen = () => setBreite(el.clientWidth);
    messen();
    // ResizeObserver statt `window.resize`: die Hülle ändert ihre Breite
    // auch ohne Fenster-Änderung (Seitenleiste, Reiter-Wechsel).
    const beobachter = new ResizeObserver(messen);
    beobachter.observe(el);
    return () => beobachter.disconnect();
  }, []);

  return (
    <div ref={huelle} className="w-full" style={{ height: hoehe }} data-testid={testId}>
      {breite > 0 ? cloneElement(children, { width: breite, height: hoehe }) : null}
    </div>
  );
}
