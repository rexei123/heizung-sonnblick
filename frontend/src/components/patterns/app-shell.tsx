/**
 * AppShell-Layout: 200 px Sidebar + Content.
 * Design-Strategie 2.0.1 § AppShell.
 */

import type { Route } from "next";
import Link from "next/link";
import type { ReactNode } from "react";

interface NavItem {
  href: Route;
  label: string;
  icon: string;
}

const NAV: NavItem[] = [
  { href: "/", label: "Übersicht", icon: "home" },
  { href: "/zimmer", label: "Zimmer", icon: "meeting_room" },
  { href: "/belegungen", label: "Belegungen", icon: "event" },
  { href: "/raumtypen", label: "Raumtypen", icon: "category" },
  { href: "/devices", label: "Geräte", icon: "thermostat" },
  { href: "/einstellungen/hotel", label: "Einstellungen", icon: "settings" },
];

export function AppShell({ children }: { children: ReactNode }): ReactNode {
  return (
    <div className="min-h-screen flex bg-bg">
      <aside
        className="w-sidebar shrink-0 border-r border-border bg-surface flex flex-col"
        aria-label="Hauptnavigation"
      >
        <div className="h-header flex items-center gap-2 px-4 border-b border-border">
          <span
            className="material-symbols-outlined text-primary"
            aria-hidden="true"
            style={{ fontSize: 26 }}
          >
            thermostat
          </span>
          <span className="font-medium text-text-primary text-base">
            Heizung Sonnblick
          </span>
        </div>
        <nav className="flex-1 p-2">
          <ul className="space-y-1">
            {NAV.map((item) => (
              <li key={item.href}>
                <Link
                  href={item.href}
                  className="flex items-center gap-3 px-3 py-2 rounded-md text-text-secondary hover:bg-surface-alt hover:text-text-primary transition-colors text-base"
                >
                  <span
                    className="material-symbols-outlined"
                    aria-hidden="true"
                    style={{ fontSize: 22 }}
                  >
                    {item.icon}
                  </span>
                  <span>{item.label}</span>
                </Link>
              </li>
            ))}
          </ul>
        </nav>
        <div className="p-3 text-xs text-text-tertiary border-t border-border">
          v0.1.x · Test-Stage
        </div>
      </aside>

      <main className="flex-1 min-w-0">{children}</main>
    </div>
  );
}
