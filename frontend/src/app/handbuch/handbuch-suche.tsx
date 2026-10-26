"use client";

/**
 * Die Suche und die Artikelliste (Paket 1).
 *
 * **Sofort beim Tippen, ohne Dienst.** Der Index kommt als Daten aus dem
 * Build; gesucht wird mit einer Schleife im Browser. Bei 24 Artikeln ist
 * das schneller als jede Abfrage, und es gibt keinen Zustand, der mit dem
 * Server auseinanderlaufen kann.
 *
 * **Der Treffer zeigt die Fundstelle** und verlinkt auf den **Abschnitt**,
 * in dem sie steht. Eine Trefferliste, die nur Titel zeigt, verlangt vom
 * Leser, den Artikel selbst zu durchsuchen — und genau das wollte er
 * nicht.
 */

import Link from "next/link";
import { useMemo, useState } from "react";

import { Input } from "@/components/ui/input";
import type { SuchEintrag } from "@/lib/handbuch/artikel";
import { MARKE_AUF, MARKE_ZU, kategorien, suche } from "@/lib/handbuch/suche";

/** Die Fundstelle mit Hervorhebung — ohne HTML aus der Zeichenkette. */
function Fundstelle({ text }: { text: string }) {
  const teile: { text: string; hervor: boolean }[] = [];
  let rest = text;
  while (true) {
    const auf = rest.indexOf(MARKE_AUF);
    if (auf === -1) break;
    const zu = rest.indexOf(MARKE_ZU, auf);
    if (zu === -1) break;
    if (auf > 0) teile.push({ text: rest.slice(0, auf), hervor: false });
    teile.push({ text: rest.slice(auf + 1, zu), hervor: true });
    rest = rest.slice(zu + 1);
  }
  if (rest !== "") teile.push({ text: rest, hervor: false });

  return (
    <span className="text-text-secondary text-xs">
      {teile.map((t, i) =>
        t.hervor ? (
          <mark key={i} className="bg-warning-soft text-text-primary rounded-sm px-0.5">
            {t.text}
          </mark>
        ) : (
          <span key={i}>{t.text}</span>
        ),
      )}
    </span>
  );
}

export function HandbuchSuche({ index }: { index: SuchEintrag[] }) {
  const [frage, setFrage] = useState("");
  const [kategorie, setKategorie] = useState("");

  const alleKategorien = useMemo(() => kategorien(index), [index]);
  const treffer = useMemo(() => suche(index, frage, kategorie), [index, frage, kategorie]);

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-end gap-3 nicht-drucken">
        <label className="block min-w-[260px] flex-1">
          <span className="text-text-secondary mb-1 block text-xs">
            Suchen in Titeln, Überschriften, Text und Stichworten
          </span>
          <Input
            type="search"
            value={frage}
            onChange={(e) => setFrage(e.target.value)}
            placeholder="z. B. Wunschtemperatur, Sperre, Betriebszeit"
            aria-label="Handbuch durchsuchen"
            data-testid="handbuch-suche"
          />
        </label>
        <label className="block">
          <span className="text-text-secondary mb-1 block text-xs">Kategorie</span>
          <select
            value={kategorie}
            onChange={(e) => setKategorie(e.target.value)}
            className="border-border bg-surface focus:border-border-focus rounded-md border px-3 py-2 text-sm focus:outline-none"
            aria-label="Nach Kategorie filtern"
            data-testid="handbuch-kategorie"
          >
            <option value="">alle</option>
            {alleKategorien.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
        </label>
      </div>

      <p className="text-text-tertiary mb-3 text-xs" data-testid="handbuch-trefferzahl">
        {frage.trim() === ""
          ? `${treffer.length} Artikel`
          : `${treffer.length} Treffer für „${frage.trim()}“`}
      </p>

      {treffer.length === 0 ? (
        <p className="text-text-secondary text-sm" data-testid="handbuch-kein-treffer">
          Kein Treffer. Die Suche vergleicht Zeichenfolgen und rät nicht —
          versuchen Sie ein kürzeres Wort.
        </p>
      ) : (
        <ul className="divide-border divide-y">
          {treffer.map((t) => (
            <li key={`${t.slug}-${t.anker ?? ""}`} className="py-3">
              <Link
                href={
                  (t.anker !== undefined
                    ? `/handbuch/${t.slug}#${t.anker}`
                    : `/handbuch/${t.slug}`) as never
                }
                className="block"
                data-testid="handbuch-treffer"
              >
                <span className="text-text-primary text-sm font-medium">{t.titel}</span>
                <span className="text-text-tertiary ml-2 text-xs">{t.kategorie}</span>
                {t.rollen === "admin" ? (
                  <span className="bg-surface-alt text-text-tertiary ml-2 rounded-sm px-1.5 py-0.5 text-[10px]">
                    Administrator
                  </span>
                ) : null}
              </Link>
              {t.stelle !== "" ? (
                <div className="mt-1">
                  <Fundstelle text={t.stelle} />
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
