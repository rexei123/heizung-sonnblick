import { ImageResponse } from "next/og";

/**
 * Favicon — N-12 (QA-Audit).
 *
 * Generiert via Next.js `app/icon.tsx`-Konvention: einfaches
 * Thermostat-Symbol (Material-Symbols-Style) mit Heizung-Sonnblick-
 * Primary-Color. Kein Bild-Asset noetig.
 */
export const size = { width: 32, height: 32 };
export const contentType = "image/png";

export default function Icon() {
  return new ImageResponse(
    (
      <div
        style={{
          fontSize: 22,
          background: "#0F4C81",
          color: "white",
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          borderRadius: 6,
          fontFamily: "sans-serif",
          fontWeight: 700,
        }}
      >
        H
      </div>
    ),
    {
      ...size,
    }
  );
}
