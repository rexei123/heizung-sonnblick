/**
 * Ein Handbuch-Artikel (Paket 1).
 *
 * **Statisch gebaut, eine Seite je Datei.** `generateStaticParams` zählt
 * die Dateien beim Bauen auf; `dynamicParams = false` sorgt dafür, dass
 * eine unbekannte Adresse die 404-Seite zeigt statt zur Laufzeit in den
 * Dateien zu suchen, die im Abbild nicht liegen. Dieselbe Begründung wie
 * in der Übersicht.
 *
 * **Das Inhaltsverzeichnis steht über dem Text, nicht daneben.** Auf dem
 * Telefon der Rezeption ist keine Spalte frei, und ein Verzeichnis, das
 * nur am großen Bildschirm erscheint, wird beim Schreiben der Artikel
 * nicht mitgedacht.
 */

import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { HandbuchInhalt } from "@/components/patterns/handbuch-inhalt";
import { ladeArtikel, ladeArtikelNachSlug } from "@/lib/handbuch/artikel";

export const dynamic = "error";
export const dynamicParams = false;

interface Props {
  params: { slug: string };
}

export function generateStaticParams(): { slug: string }[] {
  return ladeArtikel().map((a) => ({ slug: a.slug }));
}

export function generateMetadata({ params }: Props): Metadata {
  const artikel = ladeArtikelNachSlug(params.slug);
  return {
    title: artikel === undefined ? "Handbuch" : `${artikel.titel} | Handbuch`,
  };
}

export default function ArtikelSeite({ params }: Props) {
  const artikel = ladeArtikelNachSlug(params.slug);
  if (artikel === undefined) {
    notFound();
  }

  return (
    <div className="p-6 max-w-content mx-auto">
      <nav className="mb-4 text-sm nicht-drucken" aria-label="Zurück zum Handbuch">
        <Link href="/handbuch" className="text-primary hover:underline">
          ← Handbuch
        </Link>
      </nav>

      <header className="mb-6">
        <p className="text-text-tertiary text-xs">{artikel.kategorie}</p>
        <h1 className="text-2xl font-medium text-text-primary">{artikel.titel}</h1>
        <p className="text-text-tertiary mt-1 text-xs">
          Stand {artikel.stand === "" ? "— ohne Datum" : artikel.stand}
          {artikel.rollen === "admin"
            ? " · beschreibt Einstellungen, die nur Administratoren ändern können"
            : null}
        </p>
        {artikel.route !== undefined ? (
          <p className="mt-2 text-sm nicht-drucken">
            <Link href={artikel.route as never} className="text-primary hover:underline">
              Zur Seite in der Software →
            </Link>
          </p>
        ) : null}
      </header>

      {/* Ab drei Abschnitten lohnt ein Verzeichnis; darunter ist es
          Rahmen ohne Inhalt. */}
      {artikel.abschnitte.length >= 3 ? (
        <nav
          className="bg-surface-alt border-border mb-6 rounded-md border p-4 nicht-drucken"
          aria-label="Inhalt dieses Artikels"
        >
          <p className="text-text-tertiary mb-2 text-xs">In diesem Artikel</p>
          <ul className="space-y-1 text-sm">
            {artikel.abschnitte.map((a) => (
              <li key={a.anker}>
                <a href={`#${a.anker}`} className="text-primary hover:underline">
                  {a.text}
                </a>
              </li>
            ))}
          </ul>
        </nav>
      ) : null}

      <HandbuchInhalt blöcke={artikel.blöcke} />
    </div>
  );
}
