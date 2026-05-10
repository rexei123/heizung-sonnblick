import type { Metadata, Viewport } from "next";
import { Roboto } from "next/font/google";

import { AppShell } from "@/components/patterns/app-shell";
import { Providers } from "@/components/providers";

import "./globals.css";

/**
 * Roboto als verbindliche UI-Schrift gemäß Design-Strategie 2.0.
 */
const roboto = Roboto({
  subsets: ["latin"],
  weight: ["300", "400", "500", "700"],
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
      <head>
        {/* Material Symbols als Link-Tag — robuster als @import in CSS,
            Next.js kann das preloaden + Build-Optimizer fasst es nicht an. */}
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@20..48,300..700,0..1,-50..200&display=block"
        />
      </head>
      <body className="font-sans bg-bg text-text-primary antialiased">
        <Providers>
          <AppShell>{children}</AppShell>
        </Providers>
      </body>
    </html>
  );
}
