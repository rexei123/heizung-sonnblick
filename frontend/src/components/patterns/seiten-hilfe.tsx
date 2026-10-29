"use client";

/**
 * Die Kontext-Hilfe: ein „?" auf jeder Seite (Paket 1).
 *
 * **Eine Stelle, nicht fünfzehn.** Der Knopf sitzt in der Hülle der
 * Anwendung und findet den Artikel über die aktuelle Adresse. Hätte jede
 * Seite ihren eigenen Knopf, wäre die Frage „hat diese Seite eine Hilfe"
 * fünfzehnmal zu beantworten — und bei der sechzehnten Seite
 * vergessen.
 *
 * **Er öffnet einen neuen Reiter.** Wer das „?" mitten in einem
 * halb gefüllten Formular drückt, soll das Formular nicht verlieren.
 * Darum steht es auch in der Beschriftung: ein Link, der den Reiter
 * wechselt, ohne es zu sagen, ist eine Überraschung.
 *
 * **Auf Seiten ohne Artikel erscheint er nicht.** Ein „?", das auf eine
 * leere Seite führt, ist schlimmer als keines — es verbraucht das
 * Zutrauen, das die Hilfe auf den anderen Seiten braucht (§5.79, eine
 * Ebene höher: ein Melder, dem niemand glaubt).
 */

import { usePathname } from "next/navigation";

import { artikelZurRoute } from "@/lib/handbuch/routen";

export function SeitenHilfe() {
  const pfad = usePathname() ?? "/";
  const slug = artikelZurRoute(pfad);

  if (slug === undefined) {
    return null;
  }

  return (
    <a
      href={`/handbuch/${slug}`}
      target="_blank"
      rel="noreferrer noopener"
      title="Handbuch zu dieser Seite"
      aria-label="Handbuch zu dieser Seite öffnen (neuer Reiter)"
      data-testid="seiten-hilfe"
      className="nicht-drucken border-border bg-surface text-text-secondary hover:border-primary hover:text-primary fixed bottom-4 right-4 z-40 flex h-11 w-11 items-center justify-center rounded-full border shadow-md transition-colors"
    >
      <span className="material-symbols-outlined" aria-hidden style={{ fontSize: 24 }}>
        help
      </span>
    </a>
  );
}
