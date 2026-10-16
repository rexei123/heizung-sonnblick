/**
 * Welche Seiten ohne Anmeldung erreichbar sind — und wohin ein
 * Nicht-Angemeldeter geschickt wird (Hotfix 16.10.2026).
 *
 * **Der Anlass.** Ohne gültige Sitzung zeigte `https://heizung.hoteltec.at/`
 * das Dashboard-Gerüst mit „Wert nicht verfügbar" auf allen Kacheln, ohne
 * Konto in der Seitenleiste und **ohne Weg zur Anmeldung**. Belegt am
 * 16.10.2026 gegen `05caaf3`:
 *
 * 1. Das Projekt hat **kein** `middleware.ts` — serverseitig schützt im
 *    Frontend nichts einen Pfad.
 * 2. `AuthProvider.refreshUser` setzte bei 401 nur `user = null` und leitete
 *    **nicht** um; beide Zweige des `if` taten dasselbe.
 * 3. Der Docstring daneben behauptete das Gegenteil: „Bei 401 … wird
 *    automatisch auf `/login` umgeleitet (siehe `handleApiError` in
 *    `use-inactivity-logout.ts`)". **Diese Funktion gibt es im ganzen Repo
 *    nicht** — die einzige Fundstelle war der Satz selbst (§5.20).
 *
 * Es ist **keine** Regression aus Sprint 21/22: `auth-context.tsx` hat genau
 * einen Commit in seiner Geschichte (`d879fd6`, Sprint 9.17, 14.05.2026).
 * Der Zustand bestand also seit dem Tag, an dem die Anmeldung eingebaut
 * wurde.
 *
 * **Warum es niemandem auffiel, und was es nicht war:** die Daten waren nie
 * offen. Alle Endpunkte hängen an `require_user`, die Kacheln zeigten
 * deshalb „Wert nicht verfügbar" statt Zahlen. Es war ein Bedien- und
 * Vertrauensfehler — wer ein leeres Dashboard sieht, hält die Anlage für
 * defekt und nicht sich für abgemeldet (§5.30: Verstecken ist keine
 * Zugangsbeschränkung, hier in der Gegenrichtung).
 */

/**
 * Seiten, die **ohne** Anmeldung erreichbar sein müssen.
 *
 * `/login` und `/auth/*` (dort liegt der Passwort-Wechsel im
 * Forced-Change-Flow). Dieselbe Liste wie in `AppShell` — sie steht hier,
 * damit es **eine** Quelle gibt: ein Wächter, der eine andere Liste benutzt
 * als die Hülle, leitet entweder zu oft um (Endlosschleife auf `/login`)
 * oder zu selten (§5.53).
 */
export function istOeffentlicheRoute(pathname: string): boolean {
  return pathname === "/login" || pathname.startsWith("/auth/");
}

/**
 * Das Anmelde-Ziel für einen Pfad, mit Rückweg im `next`-Parameter.
 *
 * Eine öffentliche Route kommt **nicht** in `next` — sonst landet man nach
 * der Anmeldung wieder auf `/login`.
 */
export function loginZielFuer(pathname: string, search = ""): string {
  if (istOeffentlicheRoute(pathname)) return "/login";
  // Das Dashboard ist nach der Anmeldung ohnehin das Ziel — ein
  // `?next=%2F` waere Rauschen in der Adresszeile des haeufigsten Falls.
  if (pathname === "/" && search === "") return "/login";
  const ziel = `${pathname}${search}`;
  return `/login?next=${encodeURIComponent(ziel)}`;
}

/**
 * Wohin nach erfolgreicher Anmeldung — der geprüfte `next`-Parameter.
 *
 * **Nur repo-eigene Pfade.** Erlaubt ist ein einzelner `/` am Anfang;
 * abgewiesen werden `//host` (protokoll-relativ, führt auf eine fremde
 * Seite), `http://…`, `javascript:` und alles ohne führenden `/`. Ohne
 * diese Prüfung wäre `?next=` eine offene Weiterleitung: ein Link in einer
 * Mail könnte nach der Anmeldung auf eine nachgebaute Seite führen, und der
 * Nutzer hätte dort gerade erst sein Passwort getippt.
 *
 * Eine öffentliche Route als `next` ergibt `/` — sonst schickt die
 * Anmeldung zurück zur Anmeldung.
 */
export function naechsteSeiteAus(next: string | null | undefined): string {
  if (!next) return "/";
  if (!next.startsWith("/") || next.startsWith("//")) return "/";
  const pfad = next.split("?")[0] ?? next;
  if (istOeffentlicheRoute(pfad)) return "/";
  return next;
}

/**
 * Ein Flag gegen mehrfaches Umleiten.
 *
 * Läuft eine Sitzung ab, während fünf Abfragen offen sind, meldet jede
 * einzeln 401. Ohne dieses Flag würde jede davon eine Navigation auslösen —
 * die letzte gewinnt, und der `next`-Parameter wäre der der letzten
 * Antwort statt der Seite, auf der der Nutzer steht.
 */
let leitetUm = false;

/**
 * Harte Navigation auf die Anmeldung, nach einem 401 **während** der
 * Nutzung.
 *
 * Bewusst `location.assign` und nicht der Next-Router: die Sitzung ist weg,
 * und mit ihr soll der gesamte Zustand im Speicher weg sein (TanStack-Cache,
 * Formular-Entwürfe mit Gästedaten). Ein Soft-Navigate ließe beides stehen.
 *
 * Auf öffentlichen Routen passiert nichts — ein 401 auf `/login` ist ein
 * falsches Passwort und keine abgelaufene Sitzung.
 */
export function aufAnmeldungUmleiten(): void {
  if (typeof window === "undefined") return;
  if (leitetUm) return;
  const { pathname, search } = window.location;
  if (istOeffentlicheRoute(pathname)) return;
  leitetUm = true;
  window.location.assign(loginZielFuer(pathname, search));
}

/** Nur für Tests: das Flag zurücksetzen. */
export function _umleitungZuruecksetzen(): void {
  leitetUm = false;
}
