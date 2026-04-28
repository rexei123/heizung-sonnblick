import type { Metadata, Viewport } from "next";
import { Roboto } from "next/font/google";

import { Providers } from "@/components/providers";
import "./globals.css";

/**
 * Roboto als verbindliche UI-Schrift gemäß Design-Strategie 2.0.
 * Wird als CSS-Variable --font-admin exposed und in globals.css/tailwind.config.ts referenziert.
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
      <body className="font-sans bg-bg text-text-primary antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
