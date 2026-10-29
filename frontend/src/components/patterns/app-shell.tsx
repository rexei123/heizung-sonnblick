"use client";

/**
 * AppShell — Layout mit Sidebar (Sprint 9.13b: Migration auf 14 Eintraege
 * in 5 Gruppen). Desktop: fixe 200-px-Sidebar links. Mobile (<md): Off-
 * Canvas-Sheet via shadcn, Hamburger im Top-Header.
 *
 * Aktiver Route-Highlight: usePathname + startsWith fuer Untermenue-Match.
 * Pairing (`/devices/pair`) und Algorithmenverlauf (Tab in /zimmer/[id])
 * sind bewusst KEINE Sidebar-Eintraege — siehe ARCHITEKTUR-REFRESH §6.
 */

import type { Route } from "next";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, type ReactNode } from "react";

import { SeitenHilfe } from "@/components/patterns/seiten-hilfe";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { useAuth } from "@/contexts/auth-context";
import { darfBenutzerVerwalten } from "@/lib/auth/rechte";
import { istOeffentlicheRoute } from "@/lib/auth/routen";

interface NavItem {
  href: Route;
  label: string;
  icon: string;
  /**
   * Sprint 22 T6: Eintrag nur für Administratoren.
   *
   * **Genau ein Eintrag trägt das**, und zwar „Benutzer": dort gibt es für
   * einen Mitarbeiter nichts zu lesen (fremde E-Mail-Adressen, Rollen,
   * Aktiv-Kennzeichen — `GET /users` ist deshalb schon serverseitig
   * `require_admin`, §5.30 nennt diese Ausnahme ausdrücklich).
   *
   * Die Konfigurations-Seiten bleiben bewusst **sichtbar**: ihre Werte sind
   * Betriebswissen (ab wann wird abgesenkt, ist die Belegungsliste von
   * heute da), und eine verschwundene Seite erzeugt die Frage „wo ist das
   * hin" statt der Antwort „das darf ich nicht ändern". Seit T4 sagen sie
   * das selbst.
   */
  nurAdmin?: boolean;
}

interface NavGroup {
  label: string;
  items: NavItem[];
}

const NAV: NavGroup[] = [
  {
    label: "Übersicht",
    items: [
      { href: "/", label: "Dashboard", icon: "home" },
      { href: "/zimmer", label: "Zimmerübersicht", icon: "meeting_room" },
      { href: "/belegungen", label: "Belegungen", icon: "event" },
      // Paket 1, Platz korrigiert am 26.10.2026: das Handbuch stand
      // zuerst in einer eigenen Gruppe „Hilfe" am Ende der Leiste.
      // Entscheidung des Betreibers — es gehoert nach oben, zu den
      // Seiten, die man ohne Anlass oeffnet. Eine eigene Gruppe fuer
      // einen Eintrag war ohnehin eine Ueberschrift ohne Inhalt.
      { href: "/handbuch", label: "Handbuch", icon: "menu_book" },
    ],
  },
  {
    label: "Steuerung",
    items: [
      {
        href: "/einstellungen/temperaturen-zeiten",
        label: "Temperaturen & Zeiten",
        icon: "schedule",
      },
      { href: "/raumtypen", label: "Raumtypen", icon: "category" },
      { href: "/profile", label: "Profile", icon: "assignment_ind" },
      { href: "/szenarien", label: "Szenarien", icon: "movie" },
    ],
  },
  {
    label: "Geräte",
    items: [
      { href: "/devices", label: "Thermostate", icon: "thermostat" },
      { href: "/einstellungen/gateway", label: "Gateway", icon: "router" },
    ],
  },
  {
    label: "Analyse",
    items: [
      {
        href: "/analyse/temperaturverlauf",
        label: "Temperaturverlauf",
        icon: "monitoring",
      },
    ],
  },
  {
    label: "Einstellungen",
    items: [
      { href: "/einstellungen/hotel", label: "Hotel", icon: "apartment" },
      { href: "/einstellungen/saison", label: "Saison", icon: "wb_sunny" },
      { href: "/einstellungen/benutzer", label: "Benutzer", icon: "group", nurAdmin: true },
      { href: "/einstellungen/api", label: "API & Webhooks", icon: "api" },
    ],
  },
];

/**
 * Untermenue-tolerantes Active-Match: `/zimmer/123` matcht `/zimmer`.
 * Spezialfall fuer `/`: nur exakter Match (sonst matcht es alles).
 * `/einstellungen/hotel` matcht NICHT `/einstellungen/saison` —
 * `startsWith` mit "/" am Ende verhindert das.
 */
function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(href + "/");
}

function NavList({
  pathname,
  onNavigate,
}: {
  pathname: string;
  onNavigate?: () => void;
}): ReactNode {
  // Sprint 22 T6: Einträge mit `nurAdmin` fallen für alle anderen weg.
  // Eine Gruppe, die dadurch leer würde, verschwindet mit — eine
  // Überschrift ohne Einträge sieht aus wie ein Ladefehler.
  const { user } = useAuth();
  const sichtbar = NAV.map((group) => ({
    ...group,
    items: group.items.filter((item) => !item.nurAdmin || darfBenutzerVerwalten(user)),
  })).filter((group) => group.items.length > 0);

  return (
    <nav className="flex-1 overflow-y-auto p-2" aria-label="Hauptnavigation">
      <ul className="space-y-4">
        {sichtbar.map((group) => (
          <li key={group.label}>
            <h3 className="px-3 mb-1 text-xs uppercase tracking-wider text-text-tertiary font-medium">
              {group.label}
            </h3>
            <ul className="space-y-1">
              {group.items.map((item) => {
                const active = isActive(pathname, item.href);
                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      onClick={onNavigate}
                      className={`flex items-center gap-3 px-3 py-2 rounded-md transition-colors text-base ${
                        active
                          ? "bg-primary-soft text-primary font-medium"
                          : "text-text-secondary hover:bg-surface-alt hover:text-text-primary"
                      }`}
                      aria-current={active ? "page" : undefined}
                    >
                      <span
                        className="material-symbols-outlined"
                        aria-hidden
                        style={{ fontSize: 22 }}
                      >
                        {item.icon}
                      </span>
                      <span>{item.label}</span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          </li>
        ))}
      </ul>
    </nav>
  );
}

function SidebarBrand(): ReactNode {
  return (
    <div className="h-header flex items-center gap-2 px-4 border-b border-border shrink-0">
      <span
        className="material-symbols-outlined text-primary"
        aria-hidden
        style={{ fontSize: 26 }}
      >
        thermostat
      </span>
      <span className="font-medium text-text-primary text-base">
        Heizung Sonnblick
      </span>
    </div>
  );
}

function SidebarFooter(): ReactNode {
  const { user, logout } = useAuth();
  return (
    <div className="p-3 text-xs text-text-tertiary border-t border-border shrink-0 space-y-2">
      {user ? (
        <div className="flex items-center justify-between gap-2">
          <div className="flex-1 min-w-0">
            <div
              className="text-text-primary truncate"
              title={user.email}
            >
              {user.email}
            </div>
            <div className="text-text-tertiary">
              {user.role === "admin" ? "Administrator" : "Mitarbeiter"}
            </div>
          </div>
          <button
            type="button"
            onClick={() => void logout()}
            aria-label="Abmelden"
            title="Abmelden"
            className="text-text-secondary hover:text-text-primary"
          >
            <span
              className="material-symbols-outlined"
              aria-hidden
              style={{ fontSize: 20 }}
            >
              logout
            </span>
          </button>
        </div>
      ) : null}
      {/* Die Zeile stand bis 15.10.2026 als „v0.1.x · Test-Stage" da, und
          beides war falsch: die Version war seit Sprint 9 nicht nachgezogen,
          und „Test" liest das Personal als „das ist nicht das echte System".
          Dieser Server **ist** die Produktion (AE-67, Promote 09.06.2026) —
          `STAGE=test` bleibt serverseitig, weil daran Deploy-Pfade haengen,
          aber es ist eine Angabe fuer den Betrieb und keine fuer den
          Bildschirm. Die Version kommt aus `package.json` (next.config.mjs). */}
      <div>v{process.env.NEXT_PUBLIC_APP_VERSION}</div>
    </div>
  );
}

/**
 * Pre-Login-Routen: /login (B-9.17b-2) + /auth/* (z. B. /auth/change-password
 * im Forced-Change-Flow). Auf diesen Routen rendert AppShell ohne Sidebar,
 * sonst war beim Logout-Redirect die Navigation kurz auf /login sichtbar
 * (Befund 2026-05-15) und die Brand wuerde Hotelier-Daten leaken.
 *
 * Die Liste selbst liegt seit dem Hotfix vom 16.10.2026 in
 * ``lib/auth/routen`` — der Anmelde-Waechter braucht genau dieselbe, und
 * zwei Listen waeren eine zweite Wahrheit (§5.53).
 */
const isPreLoginRoute = istOeffentlicheRoute;

export function AppShell({ children }: { children: ReactNode }): ReactNode {
  const pathname = usePathname() ?? "/";
  const [mobileOpen, setMobileOpen] = useState(false);

  if (isPreLoginRoute(pathname)) {
    return <main className="min-h-screen bg-bg">{children}</main>;
  }

  return (
    <div className="min-h-screen flex flex-col md:flex-row bg-bg">
      {/* Mobile-Top-Bar mit Hamburger (nur unter md) */}
      <header className="md:hidden h-header flex items-center gap-2 px-4 border-b border-border bg-surface shrink-0">
        <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
          <SheetTrigger asChild>
            <button
              type="button"
              className="p-2 -ml-2 text-text-secondary hover:text-text-primary"
              aria-label="Navigation öffnen"
            >
              <span className="material-symbols-outlined" aria-hidden style={{ fontSize: 24 }}>
                menu
              </span>
            </button>
          </SheetTrigger>
          <SheetContent side="left" className="p-0 w-sidebar flex flex-col gap-0">
            <SheetTitle className="sr-only">Navigation</SheetTitle>
            <SheetDescription className="sr-only">
              Hauptnavigation der Heizungssteuerung
            </SheetDescription>
            <SidebarBrand />
            <NavList pathname={pathname} onNavigate={() => setMobileOpen(false)} />
            <SidebarFooter />
          </SheetContent>
        </Sheet>
        <span
          className="material-symbols-outlined text-primary ml-2"
          aria-hidden
          style={{ fontSize: 22 }}
        >
          thermostat
        </span>
        <span className="font-medium text-text-primary">Heizung Sonnblick</span>
      </header>

      {/* Desktop-Sidebar (nur ab md) */}
      <aside
        className="hidden md:flex w-sidebar shrink-0 border-r border-border bg-surface flex-col"
        aria-label="Hauptnavigation"
      >
        <SidebarBrand />
        <NavList pathname={pathname} />
        <SidebarFooter />
      </aside>

      <main className="flex-1 min-w-0">{children}</main>

      {/* Paket 1: das „?" zur aktuellen Seite. Steht hier und nicht in
          den Seiten, damit es keine Seite gibt, die es vergisst. Vor der
          Anmeldung erscheint es nicht — der Zweig oben kehrt vorher
          zurück. */}
      <SeitenHilfe />
    </div>
  );
}
