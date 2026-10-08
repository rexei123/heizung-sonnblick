import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";
import { Toaster } from "sonner";

import { AppShell } from "@/components/patterns/app-shell";
import { Providers } from "@/components/providers";

import "./globals.css";

/**
 * Roboto als verbindliche UI-Schrift gemäß Design-Strategie 2.0.
 *
 * **Aus dem Repo, nicht von Google (Befund 08.10.2026).** Vorher stand hier
 * `next/font/google`, und das holt die Schrift zur **Build-Zeit** von
 * fonts.googleapis.com. Jeder CI-Lauf und jeder Image-Build hing damit an
 * einem fremden Dienst.
 *
 * Am 08.10. hat das zweimal binnen einer Stunde CI gekippt — einmal den
 * e2e-Lauf von PR #275, einmal den Build von PR #277 —, beide Male mit
 * dieser Meldung:
 *
 *     An error occurred in `next/font`.
 *     TypeError: Cannot read properties of null (reading '1')
 *
 * Die Meldung nennt die Ursache nicht: sie entsteht, wenn der Abruf
 * fehlschlägt und Next.js danach auf einem `null`-Treffer weiterrechnet.
 * Sie liest sich wie ein Code-Fehler, und bei #275 habe ich drei Abfragen
 * gebraucht, um sie als Transient zu erkennen.
 *
 * **Für H-6 ist das mehr als Lästigkeit.** Weg C stellt die Invariante her,
 * dass jeder Commit einen Image-Tag hat; ein fehlgeschlagener Build ist ein
 * Commit **ohne** Tag. Der Rückfall auf Build fängt es ab, aber die
 * Invariante hing an einem Dienst, der nichts mit diesem Haus zu tun hat.
 *
 * Die Datei ist das **Variable-Font-Subset** `latin` aus Roboto v51 (43 KB).
 * Google Fonts liefert für alle vier bisher angeforderten Schnitte
 * (300/400/500/700) dieselbe URL — es ist eine Datei, die den ganzen
 * Gewichtsbereich trägt. Deshalb `weight: "100 900"` statt vier Einträge.
 *
 * Lizenz: Apache-2.0, siehe `fonts/LICENSE.txt`. Bündeln ist ausdrücklich
 * erlaubt.
 *
 * **Wenn ein weiteres Subset gebraucht wird** (die Oberfläche ist deutsch,
 * `latin` genügt heute): die Datei neben diese legen und hier ergänzen.
 * Nicht auf `next/font/google` zurückgehen — der Grund steht oben.
 */
const roboto = localFont({
  src: "./fonts/roboto-latin-variable.woff2",
  weight: "100 900",
  style: "normal",
  variable: "--font-admin",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Heizungssteuerung | Hotel Sonnblick",
  description: "Heizungssteuerung Hotel Sonnblick Kaprun",
  applicationName: "Heizung Sonnblick",
  formatDetection: {
    telephone: false,
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  // user-scalable=no ist NICHT gesetzt — barrierefreies Zoomen muss möglich bleiben.
  themeColor: "#dd3c71",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="de" className={roboto.variable}>
      <body className="font-sans bg-bg text-text-primary antialiased">
        <Providers>
          <AppShell>{children}</AppShell>
        </Providers>
        {/* Sprint 13b.2 T0.6: Toast-Slot oberhalb der App, ausserhalb
            Providers (Toaster braucht keinen QueryClient-Context). */}
        <Toaster position="top-right" richColors closeButton />
      </body>
    </html>
  );
}
